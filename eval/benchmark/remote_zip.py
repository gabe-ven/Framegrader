"""Read individual members out of a remote zip without downloading all of it.

The datasets this benchmark uses ship as single multi-gigabyte zips (CADB
~2 GB, KonIQ 0.8-5.6 GB), but each run needs only a few hundred images. Every
host involved supports HTTP Range requests, and a zip's central directory sits
at the end of the file — so `zipfile` can be pointed at a seekable file object
backed by ranged GETs, read the directory (a few hundred KB), and then fetch
exactly the sampled members. A 500-image KonIQ sample costs ~60 MB of transfer
instead of 767 MB.

Standard library only (urllib), so the downloader has no dependencies of its
own.
"""

from __future__ import annotations

import io
import struct
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections import OrderedDict

_USER_AGENT = "framegrader-benchmark/1.0 (+https://github.com/gabe-ven/framegrader)"
_BLOCK = 256 * 1024  # bytes per ranged GET; zip headers are tiny, so cache blocks
_MAX_CACHED_BLOCKS = 64


class HttpRangeFile(io.RawIOBase):
    """A read-only, seekable file over HTTP Range requests, with a block cache."""

    def __init__(self, url: str, *, retries: int = 4, timeout: float = 60.0) -> None:
        super().__init__()
        self._origin = url
        self._url = url
        # Set once a host refuses a reused redirect target (Dropbox), so later
        # requests go straight through the origin instead of failing first.
        self._sticky_origin = False
        self._retries = retries
        self._timeout = timeout
        self._pos = 0
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self.bytes_fetched = 0
        # One probe resolves redirects (DaRUS -> presigned S3, Dropbox -> CDN)
        # and learns the total size from Content-Range.
        with self._get(0, 0, self._url) as resp:
            if not self._sticky_origin:
                self._url = resp.geturl()
            content_range = resp.headers.get("Content-Range", "")
            if resp.status != 206 or "/" not in content_range:
                raise OSError(f"{url} does not support HTTP range requests")
            self.size = int(content_range.rsplit("/", 1)[1])

    def _get(self, start: int, end: int, url: str):
        req = urllib.request.Request(
            url, headers={"Range": f"bytes={start}-{end}", "User-Agent": _USER_AGENT}
        )
        delay = 1.0
        for attempt in range(self._retries + 1):
            try:
                return urllib.request.urlopen(req, timeout=self._timeout)
            except urllib.error.HTTPError as exc:
                # Some hosts (Dropbox) hand out redirect targets that can't be
                # reused across requests. Go back through the original URL.
                if exc.code in (401, 403, 410) and url != self._origin:
                    url = self._url = self._origin
                    self._sticky_origin = True
                    req = urllib.request.Request(
                        url, headers={"Range": f"bytes={start}-{end}", "User-Agent": _USER_AGENT}
                    )
                    continue
                if exc.code < 500 or attempt == self._retries:
                    raise
                time.sleep(delay)
                delay *= 2
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == self._retries:
                    raise
                time.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    def _block(self, index: int) -> bytes:
        cached = self._cache.get(index)
        if cached is not None:
            self._cache.move_to_end(index)
            return cached
        start = index * _BLOCK
        end = min(self.size, start + _BLOCK) - 1
        with self._get(start, end, self._url) as resp:
            data = resp.read()
        self.bytes_fetched += len(data)
        self._cache[index] = data
        if len(self._cache) > _MAX_CACHED_BLOCKS:
            self._cache.popitem(last=False)
        return data

    # -- io.RawIOBase ------------------------------------------------------

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self.size + offset
        self._pos = max(0, min(self._pos, self.size))
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        n = min(n, self.size - self._pos)
        if n <= 0:
            return b""
        # Large member reads bypass the cache: one GET for the whole span.
        if n > 4 * _BLOCK:
            with self._get(self._pos, self._pos + n - 1, self._url) as resp:
                data = resp.read()
            self.bytes_fetched += len(data)
        else:
            chunks = []
            pos, remaining = self._pos, n
            while remaining > 0:
                index, offset = divmod(pos, _BLOCK)
                block = self._block(index)
                piece = block[offset : offset + remaining]
                if not piece:
                    break
                chunks.append(piece)
                pos += len(piece)
                remaining -= len(piece)
            data = b"".join(chunks)
        self._pos += len(data)
        return data

    def readinto(self, buffer) -> int:  # type: ignore[override]
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


    def fetch(self, start: int, length: int) -> bytes:
        """One ranged GET for exactly [start, start+length)."""
        end = min(self.size, start + length) - 1
        with self._get(start, end, self._url) as resp:
            if resp.status != 206:
                raise OSError(f"expected 206 Partial Content, got {resp.status}")
            data = resp.read()
        self.bytes_fetched += len(data)
        return data


# Local file header: signature, version, flags, method, time, date, crc,
# csize, usize, name length, extra length — 30 bytes.
_LOCAL_HEADER = struct.Struct("<4s5H3L2H")
# Generous allowance for the local header's name + extra field, which may
# differ from the central directory's copy.
_HEADER_SLACK = 1024


class RemoteZip(zipfile.ZipFile):
    """ZipFile whose ``read`` fetches each member in a single ranged GET.

    zipfile's own reader streams a member through the file object in small
    chunks, which over HTTP is one round trip per 256 KB block. The central
    directory already says exactly where each member lives and how big it is,
    so fetch that span once, parse the local header from memory, inflate, and
    check the CRC-32 — the same integrity guarantee zipfile gives.
    """

    remote: HttpRangeFile

    def read(self, name, pwd=None) -> bytes:  # type: ignore[override]
        # Under concurrent load a CDN occasionally answers a range request
        # with the wrong bytes (a throttling page, a truncated body). The
        # header signature and CRC catch that; retrying fixes it.
        delay = 2.0
        for attempt in range(7):
            try:
                return self._read_once(name, pwd)
            except (zipfile.BadZipFile, OSError, zlib.error):
                if attempt == 6:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
        raise AssertionError("unreachable")

    def _read_once(self, name, pwd=None) -> bytes:
        info = name if isinstance(name, zipfile.ZipInfo) else self.getinfo(name)
        blob = self.remote.fetch(info.header_offset, _HEADER_SLACK + info.compress_size)
        sig, *_rest, name_len, extra_len = _LOCAL_HEADER.unpack_from(blob)
        if sig != b"PK\x03\x04":
            raise zipfile.BadZipFile(f"bad local header for {info.filename}")
        start = _LOCAL_HEADER.size + name_len + extra_len
        payload = blob[start : start + info.compress_size]
        if len(payload) < info.compress_size:  # header bigger than the slack
            payload += self.remote.fetch(
                info.header_offset + start + len(payload), info.compress_size - len(payload)
            )
        if info.compress_type == zipfile.ZIP_STORED:
            data = payload
        elif info.compress_type == zipfile.ZIP_DEFLATED:
            data = zlib.decompress(payload, -15)
        else:
            return super().read(info, pwd)
        if zlib.crc32(data) != info.CRC:
            raise zipfile.BadZipFile(f"CRC mismatch for {info.filename}")
        return data


def open_remote_zip(url: str) -> tuple[zipfile.ZipFile, HttpRangeFile]:
    remote = HttpRangeFile(url)
    zf = RemoteZip(io.BufferedReader(remote, buffer_size=_BLOCK))
    zf.remote = remote
    return zf, remote

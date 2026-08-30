import { useRef, useState, type DragEvent } from "react";
import { ACCEPTED_TYPES, MAX_UPLOAD_MB } from "@/lib/api";

interface DropzoneProps {
  onFile: (file: File) => void;
}

/**
 * An empty comic panel: thick black border, hard offset shadow, white
 * ground. The whole point of the neobrutalist treatment is that a control
 * should look unmistakably like a control, so this stays a plain, obvious
 * upload widget rather than anything more editorial.
 */
export function Dropzone({ onFile }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onFile(file);
  };

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`flex min-h-[220px] cursor-pointer flex-col items-center justify-center gap-3 border-4 border-black p-10 text-center shadow-[8px_8px_0_0_#000] transition-colors ${
        dragging ? "bg-yellow-100" : "bg-white"
      }`}
    >
      <svg
        aria-hidden="true"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        className="h-10 w-10 text-black"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z"
        />
      </svg>

      <p className="font-sans text-base font-black uppercase tracking-tight text-black">
        Drag &amp; drop a photograph here
      </p>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          inputRef.current?.click();
        }}
        className="mt-1 border-4 border-black bg-red-500 px-5 py-2.5 font-sans text-sm font-black uppercase tracking-tight text-white shadow-[8px_8px_0_0_#000] transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-[4px_4px_0_0_#000] active:translate-x-2 active:translate-y-2 active:shadow-none focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-yellow-400"
      >
        Choose File
      </button>

      <p className="mt-2 font-mono text-[11px] font-bold uppercase tracking-wide text-black">
        JPEG, PNG, WEBP, TIFF or BMP · up to {MAX_UPLOAD_MB}MB
      </p>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}

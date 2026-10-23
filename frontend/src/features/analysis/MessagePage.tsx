import { Link } from "react-router";

/** Full-page notice for not-found / unreachable states. */
export function MessagePage({
  title,
  body,
  retry = false,
}: {
  title: string;
  body: string;
  retry?: boolean;
}) {
  return (
    <div className="relative left-1/2 flex min-h-screen w-screen -translate-x-1/2 flex-col items-center justify-center gap-6 bg-amber-50 px-6 py-20 text-center">
      <h1 className="font-sans text-3xl font-black uppercase tracking-tight text-black">{title}</h1>
      <p className="max-w-md font-mono text-sm font-bold text-black">{body}</p>
      <div className="flex flex-wrap justify-center gap-4">
        {retry && (
          <button
            onClick={() => window.location.reload()}
            className="border-4 border-black bg-yellow-400 px-6 py-3 font-sans text-sm font-black uppercase text-black shadow-[6px_6px_0_0_#000]"
          >
            Try again
          </button>
        )}
        <Link
          to="/"
          className="border-4 border-black bg-white px-6 py-3 font-sans text-sm font-black uppercase text-black shadow-[6px_6px_0_0_#000]"
        >
          Analyze a photo
        </Link>
      </div>
    </div>
  );
}

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SafeMarkdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => (/^(https?:\/\/|mailto:)/i.test(url) ? url : "")}
        components={{
          img: () => null,
          a: ({ href, children }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          table: ({ children }) => (
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Таблица в ответе"
            >
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}

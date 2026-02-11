import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import csv from "react-syntax-highlighter/dist/esm/languages/prism/csv";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";

interface ArtifactCodePreviewProps {
  language: "json" | "xml" | "html" | "csv";
  code: string;
}

let languagesRegistered = false;

function ensureLanguagesRegistered() {
  if (languagesRegistered) return;
  SyntaxHighlighter.registerLanguage("json", json);
  SyntaxHighlighter.registerLanguage("xml", markup);
  SyntaxHighlighter.registerLanguage("html", markup);
  SyntaxHighlighter.registerLanguage("csv", csv);
  languagesRegistered = true;
}

export function ArtifactCodePreview({ language, code }: ArtifactCodePreviewProps) {
  ensureLanguagesRegistered();

  return (
    <SyntaxHighlighter
      language={language}
      style={vscDarkPlus}
      customStyle={{
        margin: 0,
        background: "transparent",
        fontSize: "11px",
        lineHeight: "1.55",
        padding: 0,
      }}
      wrapLongLines
    >
      {code}
    </SyntaxHighlighter>
  );
}


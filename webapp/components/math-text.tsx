import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const MATH_SPLIT_RE = /(\$\$[\s\S]*?\$\$|\$[^$\n][\s\S]*?\$)/g;

const LATEX_SYMBOLS: Record<string, string> = {
  le: "≤",
  ge: "≥",
  neq: "≠",
  approx: "≈",
  times: "×",
  cdot: "·",
  pm: "±",
  infty: "∞",
  sum: "∑",
  prod: "∏",
  nabla: "∇",
  Delta: "Δ",
  alpha: "α",
  beta: "β",
  gamma: "γ",
  delta: "δ",
  lambda: "λ",
  mu: "μ",
  sigma: "σ",
  theta: "θ",
  pi: "π",
};

interface MathTextProps {
  text?: string | null;
  className?: string;
}

function readArgument(input: string, start: number): { value: string; next: number } {
  let index = start;
  while (input[index] === " ") index += 1;

  if (input[index] !== "{") {
    return { value: input[index] || "", next: Math.min(index + 1, input.length) };
  }

  let depth = 0;
  for (let i = index; i < input.length; i += 1) {
    const char = input[i];
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return { value: input.slice(index + 1, i), next: i + 1 };
      }
    }
  }
  return { value: input.slice(index + 1), next: input.length };
}

function renderPlainText(text: string, keyPrefix: string): ReactNode[] {
  return text.split("\n").flatMap((line, index, lines) => {
    const nodes: ReactNode[] = [<Fragment key={`${keyPrefix}-t-${index}`}>{line}</Fragment>];
    if (index < lines.length - 1) nodes.push(<br key={`${keyPrefix}-br-${index}`} />);
    return nodes;
  });
}

function renderLatex(input: string, keyPrefix: string): ReactNode[] {
  const latex = input.trim().replace(/\\\\/g, "\\");
  const nodes: ReactNode[] = [];
  let index = 0;

  while (index < latex.length) {
    const char = latex[index];

    if (char === "\\") {
      const match = latex.slice(index).match(/^\\([A-Za-z]+)/);
      if (!match) {
        nodes.push(<Fragment key={`${keyPrefix}-${index}`}>{char}</Fragment>);
        index += 1;
        continue;
      }

      const command = match[1];
      index += command.length + 1;

      if (command === "frac") {
        const numerator = readArgument(latex, index);
        const denominator = readArgument(latex, numerator.next);
        nodes.push(
          <span className="math-frac" key={`${keyPrefix}-frac-${index}`}>
            <span className="math-frac-num">
              {renderLatex(numerator.value, `${keyPrefix}-num-${index}`)}
            </span>
            <span className="math-frac-den">
              {renderLatex(denominator.value, `${keyPrefix}-den-${index}`)}
            </span>
          </span>,
        );
        index = denominator.next;
        continue;
      }

      if (command === "sqrt") {
        const arg = readArgument(latex, index);
        nodes.push(
          <span className="math-sqrt" key={`${keyPrefix}-sqrt-${index}`}>
            <span className="math-radical">√</span>
            <span className="math-radicand">
              {renderLatex(arg.value, `${keyPrefix}-sqrtarg-${index}`)}
            </span>
          </span>,
        );
        index = arg.next;
        continue;
      }

      if (command === "hat" || command === "bar") {
        const arg = readArgument(latex, index);
        nodes.push(
          <span
            className={command === "hat" ? "math-hat" : "math-bar"}
            key={`${keyPrefix}-${command}-${index}`}
          >
            {renderLatex(arg.value, `${keyPrefix}-${command}arg-${index}`)}
          </span>,
        );
        index = arg.next;
        continue;
      }

      nodes.push(
        <Fragment key={`${keyPrefix}-cmd-${index}`}>
          {LATEX_SYMBOLS[command] ?? command}
        </Fragment>,
      );
      continue;
    }

    if (char === "^" || char === "_") {
      const arg = readArgument(latex, index + 1);
      const Tag = char === "^" ? "sup" : "sub";
      nodes.push(
        <Tag key={`${keyPrefix}-${Tag}-${index}`}>
          {renderLatex(arg.value, `${keyPrefix}-${Tag}arg-${index}`)}
        </Tag>,
      );
      index = arg.next;
      continue;
    }

    if (char === "{") {
      const arg = readArgument(latex, index);
      nodes.push(
        <Fragment key={`${keyPrefix}-group-${index}`}>
          {renderLatex(arg.value, `${keyPrefix}-grouparg-${index}`)}
        </Fragment>,
      );
      index = arg.next;
      continue;
    }

    if (char === "}") {
      index += 1;
      continue;
    }

    nodes.push(<Fragment key={`${keyPrefix}-char-${index}`}>{char}</Fragment>);
    index += 1;
  }

  return nodes;
}

function normalizeDisplayInput(text: string): string {
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, expr: string) => `$$${expr}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_match, expr: string) => `$${expr}$`);
}

export function MathText({ text, className }: MathTextProps) {
  const source = normalizeDisplayInput(text || "");
  const pieces = source.split(MATH_SPLIT_RE).filter(Boolean);

  return (
    <span className={cn("math-text", className)}>
      {pieces.map((piece, index) => {
        if (piece.startsWith("$$") && piece.endsWith("$$")) {
          return (
            <span className="math-display" key={`math-block-${index}`}>
              {renderLatex(piece.slice(2, -2), `math-block-${index}`)}
            </span>
          );
        }
        if (piece.startsWith("$") && piece.endsWith("$")) {
          return (
            <span className="math-inline" key={`math-inline-${index}`}>
              {renderLatex(piece.slice(1, -1), `math-inline-${index}`)}
            </span>
          );
        }
        return (
          <Fragment key={`plain-${index}`}>
            {renderPlainText(piece, `plain-${index}`)}
          </Fragment>
        );
      })}
    </span>
  );
}

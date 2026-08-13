import { executiveDisplayName } from "../components/ExecutiveCard";

/** Helpers for isolated per-question board display (no cross-question UI leakage). */

const SYNTHESIS_SECTION_ORDER = [
  "Primary recommendation",
  "Key risks",
  "Areas of disagreement",
  "Recommended actions",
  "Metrics to monitor",
];

function extractSection(text, startLabel, nextLabels) {
  const startRe = new RegExp(`${startLabel}:\\s*`, "i");
  const startMatch = startRe.exec(text);
  if (!startMatch) return "";
  const from = startMatch.index + startMatch[0].length;
  let to = text.length;
  for (const label of nextLabels) {
    const endRe = new RegExp(`\\n${label}:`, "i");
    const rest = text.slice(from);
    const endMatch = endRe.exec(rest);
    if (endMatch) {
      to = from + endMatch.index;
      break;
    }
  }
  return text.slice(from, to).trim();
}

function parseBulletList(block) {
  if (!block) return [];
  return block
    .split("\n")
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.)])\s*/, "").trim())
    .filter(Boolean);
}

/** Reconstruct BoardSynthesis from the persisted SYNTHESIS message for the current question. */
export function parseSynthesisFromMessage(content) {
  if (!content || typeof content !== "string") return null;
  const text = content.trim();
  if (!text) return null;

  const after = (label) => {
    const idx = SYNTHESIS_SECTION_ORDER.indexOf(label);
    return SYNTHESIS_SECTION_ORDER.slice(idx + 1).concat(["Confidence"]);
  };

  const recommendation = extractSection(text, "Primary recommendation", after("Primary recommendation"));
  const keyRisks = parseBulletList(extractSection(text, "Key risks", after("Key risks")));
  const disagreements = parseBulletList(
    extractSection(text, "Areas of disagreement", after("Areas of disagreement"))
  );
  const actions = parseBulletList(extractSection(text, "Recommended actions", after("Recommended actions")));
  const metrics = parseBulletList(extractSection(text, "Metrics to monitor", after("Metrics to monitor")));
  const confidenceMatch = text.match(/Confidence:\s*(High|Medium|Low)/i);
  const confidence = confidenceMatch
    ? `${confidenceMatch[1][0].toUpperCase()}${confidenceMatch[1].slice(1).toLowerCase()}`
    : "Medium";

  if (recommendation) {
    return {
      recommendation,
      key_risks: keyRisks,
      disagreements,
      actions,
      metrics,
      confidence,
    };
  }

  // Unstructured SYNTHESIS payload: still show the stored text rather than hiding the panel.
  return {
    recommendation: text,
    key_risks: [],
    disagreements: [],
    actions: [],
    metrics: [],
    confidence,
  };
}

export function boardResultToTimeline(board) {
  if (!board?.question) return [];

  const items = [
    {
      key: "ceo-current",
      role: "CEO",
      speaker: executiveDisplayName("CEO"),
      content: board.question,
      round: null,
    },
  ];

  for (const entry of board.discussion || []) {
    items.push({
      key: `disc-${entry.role}-r${entry.round}`,
      role: entry.role,
      speaker: executiveDisplayName(entry.role),
      content: entry.content,
      round: entry.round,
    });
  }

  return items;
}

export function extractLatestBoardFromMessages(messages) {
  if (!messages?.length) return null;

  let lastCeoIndex = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === "CEO") {
      lastCeoIndex = i;
      break;
    }
  }
  if (lastCeoIndex < 0) return null;

  const slice = messages.slice(lastCeoIndex);
  const question = slice.find((m) => m.role === "CEO")?.content;
  if (!question) return null;

  const discussion = slice
    .filter((m) => m.role !== "CEO" && m.role !== "SYNTHESIS")
    .map((m) => ({
      role: m.role,
      round: m.round,
      content: m.content,
    }));

  const synthesisMessage = [...slice].reverse().find((m) => m.role === "SYNTHESIS");
  const synthesis = parseSynthesisFromMessage(synthesisMessage?.content);

  return { question, discussion, synthesis };
}

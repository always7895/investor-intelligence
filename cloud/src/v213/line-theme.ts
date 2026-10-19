import { assertLineMessages, type LineOutboundMessage } from "../line-messages";

/** Ink monochrome palette, matched to the bot's black-and-white line-art identity.
 * Hierarchy comes from lightness, not hue: a three-stop black-to-graphite
 * gradient band, an ink strip for the key section, grey strips below it.
 * No remote image fetch, new hosting, or claim that a local preview is LINE UI.
 *
 * Design system for LINE Flex surfaces. Text colours meet WCAG AA (4.5:1) on
 * the lightest surface they are used on (gradient ends included); colour never
 * replaces the explicit +/- sign. Sizes are LINE keywords only (no px).
 */
export const LINE_THEME = Object.freeze({ ink: "#111418", muted: "#4A5058", paper: "#FFFFFF",
  border: "#E5E7EB", soft: "#F4F5F7", subtle: "#5F6670", frame: "#D5D9DF",
  // Operator direction 2026-09-25: black gradient band, framed sections per level;
  // green accents read as off-brand next to the monochrome line-art (warm and plain rejected).
  headerBackground: "#000000", headerGradientCenter: "#1E2228", headerGradientEnd: "#4A525E",
  headerText: "#FFFFFF", headerMuted: "#E6E9ED", headerSubtle: "#C9CED6", headerAlert: "#FFB4AB",
  strong: "#1D2127", strongEnd: "#3A414B", slateTint: "#ECEEF1", slateTitle: "#111418",
  quietTint: "#F7F8F9", quietTitle: "#4A5058",
  button: "#ECEEF1", onAccent: "#111418", onInk: "#FFFFFF",
  // Option cycle outside its DTE window: the original yellow pill (operator 2026-09-25: red read as an error).
  cycleCaution: "#FDE68A", cycleCautionText: "#78350F",
  negative: "#B42318", paleNegative: "#FEF3F2", caution: "#9A3412", paleCaution: "#FFF7ED" });

export const menuText = (text: string, size = "sm", color: string = LINE_THEME.ink) => ({ type: "text", text, size, color, wrap: true });
export const menuBox = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", spacing: "md", contents, ...extra });
/** Shared action contract: every product button is a secondary (light grey, ink label), md-height mobile tap target. */
export const menuAction = (label: string, command: string) => ({ type: "button", style: "secondary", height: "md", color: LINE_THEME.button,
  action: { type: "message", label, text: command } });

const T = LINE_THEME;

/** Three-stop black-to-graphite gradient behind every product header; the solid colour is the fallback. */
export const headerGradient = Object.freeze({ type: "linearGradient", angle: "135deg", startColor: T.headerBackground,
  centerColor: T.headerGradientCenter, centerPosition: "45%", endColor: T.headerGradientEnd });

/** Box style shared by every product header: the dark identity band. */
export const headerStyle = Object.freeze({ backgroundColor: T.headerBackground, background: headerGradient, paddingAll: "xl" });

/** Footer shared by product cards: white ground so the grey buttons read as buttons. */
export const footerStyle = Object.freeze({ backgroundColor: T.paper, paddingAll: "md", spacing: "sm" });

/** Value colour: accounting convention, negatives in red, everything else ink; the sign stays in the text. */
export function signColor(value: string): string {
  const trimmed = value.trim();
  if (/^[-−]\d/.test(trimmed)) return T.negative;
  return /^[+\d]/.test(trimmed) ? T.ink : T.subtle;
}

export const uiText = (text: string, size = "sm", color: string = T.ink, extra: Record<string, unknown> = {}) =>
  ({ type: "text", text, size, color, wrap: true, ...extra });

export const uiBox = (contents: unknown[], extra: Record<string, unknown> = {}) =>
  ({ type: "box", layout: "vertical", spacing: "sm", contents, ...extra });

/** Rounded pill label (rank, status): an inverted white pill with ink text on the dark band. */
export const chip = (text: string, backgroundColor: string = T.paper, color: string = T.onAccent) =>
  uiBox([uiText(text, "xxs", color, { weight: "bold", align: "center" })], {
    backgroundColor, cornerRadius: "xxl", paddingStart: "md", paddingEnd: "md", paddingTop: "xs", paddingBottom: "xs",
    flex: 0, justifyContent: "center",
  });

/** Small ink heading (used outside framed sections). */
export const sectionTitle = (text: string, color: string = T.ink) => uiText(text, "xxs", color, { weight: "bold" });

/** Label immediately followed by its value (seven-field inspectors rely on this order). */
export const labelValue = (label: string, value: string, valueExtra: Record<string, unknown> = {}, flex = 1) =>
  uiBox([uiText(label, "xxs", T.subtle), uiText(value, "sm", T.ink, valueExtra)], { flex, spacing: "xs" });

/** KPI tile: muted label, large sign-coloured value. Long values step down in size. */
export const kpiTile = (label: string, value: string, color: string = signColor(value)) => uiBox([
  uiText(label, "xxs", T.subtle),
  uiText(value, value.length > 8 ? "sm" : "xl", color, { weight: "bold" }),
], { flex: 1, spacing: "xs", backgroundColor: T.soft, cornerRadius: "md", paddingAll: "md" });

/** Information levels by lightness: key (ink strip with a short gradient), detail (grey), forward/context (pale). */
const SECTION_TONES = Object.freeze({
  key: [T.strong, T.onInk], detail: [T.slateTint, T.slateTitle], context: [T.quietTint, T.quietTitle],
} as const);
export type SectionTone = keyof typeof SECTION_TONES;

const strongGradient = Object.freeze({ type: "linearGradient", angle: "90deg", startColor: T.strong, endColor: T.strongEnd });

/** Framed section: a title strip names the information level, content sits below. */
export const section = (title: string, contents: unknown[], tone: SectionTone = "detail") => {
  const [tint, titleColor] = SECTION_TONES[tone];
  return uiBox([
    uiBox([uiText(title, "sm", titleColor, { weight: "bold" })], {
      backgroundColor: tint, ...(tone === "key" ? { background: strongGradient } : {}),
      paddingStart: "md", paddingEnd: "md", paddingTop: "sm", paddingBottom: "sm",
    }),
    uiBox(contents, { paddingAll: "md", spacing: "md" }),
  ], { borderColor: T.frame, borderWidth: "light", cornerRadius: "md", spacing: "none" });
};

/** Callout panel for notes (soft grey) and warnings (caution). */
export const panel = (contents: unknown[], tone: "soft" | "neutral" | "caution" = "neutral") => uiBox(contents, {
  backgroundColor: tone === "soft" ? T.soft : tone === "caution" ? T.paleCaution : T.paper,
  borderColor: tone === "soft" ? T.frame : tone === "caution" ? "#FED7AA" : T.border,
  borderWidth: "light", cornerRadius: "md", paddingAll: "lg", spacing: "md",
});

export const divider = () => ({ type: "separator", color: T.border });

/** Shared product header: eyebrow line and bold title on the dark identity band. */
export const productHeader = (eyebrow: string, title: string, extra: unknown[] = []) => uiBox([
  uiText(eyebrow, "xxs", T.headerMuted, { weight: "bold" }),
  uiText(title, "xl", T.headerText, { weight: "bold" }),
  ...extra,
], { ...headerStyle, spacing: "sm" });

/** Compact footnote text for disclosures that must remain visible. */
export const footnote = (text: string) => uiText(text, "xxs", T.subtle);

// Body visuals (operator 2026-09-25: card bodies read as flat text). Text keeps LINE size keywords;
// decorative shapes (bars, dots, rails) use px thickness exactly like LINE's own showcase layouts.

/** Figures inside running text: signed changes, money and percentages (a hyphen inside a date is not a sign). */
const FIGURE = /((?<![\w.$-])[+\-−]\d[\d,]*(?:\.\d+)?\s?(?:%|個百分點|pp)?(?![\d-])|US\$[\d,]+(?:\.\d+)?[BMK]?|(?<![\w.])\d[\d,]*(?:\.\d+)?%)/g;

/** Wrapped text whose figures are bold (negatives red, by the accounting convention). With spans LINE ignores `text`,
 * so it is omitted to keep carousels under the 50 KB cap; visible text is the spans joined. */
export function richText(text: string, size = "xs", color: string = T.ink, extra: Record<string, unknown> = {}) {
  const parts = text.split(FIGURE).filter(part => part.length > 0);
  if (parts.length < 2 || parts.length > 60) return uiText(text, size, color, extra);
  const spans = parts.map(part => new RegExp(`^${FIGURE.source}$`).test(part)
    ? { type: "span", text: part, weight: "bold", color: /^[-−]\d/.test(part) ? T.negative : T.ink }
    : { type: "span", text: part, color });
  return { type: "text", size, color, wrap: true, contents: spans, ...extra };
}

const clampPct = (value: number) => Math.max(0, Math.min(100, Math.round(value)));

/** Horizontal meter: a pale track with an ink fill proportional to value/max. `grow` only inside a horizontal row
 * (in a vertical box flex would stretch the track downwards). */
export const meter = (value: number, max = 100, fill: string = T.ink, grow = false) => ({
  type: "box", layout: "vertical", backgroundColor: T.border, height: "6px", cornerRadius: "3px", ...(grow ? { flex: 1 } : {}),
  contents: [{ type: "box", layout: "vertical", contents: [], width: `${Math.max(2, clampPct((value / max) * 100))}%`,
    height: "6px", cornerRadius: "3px", background: { type: "linearGradient", angle: "90deg", startColor: T.strongEnd, endColor: fill }, backgroundColor: fill }],
});

/** Square rank badge: the leader is solid ink, the rest graphite outline. */
export const rankBadge = (rank: number | string, lead = false) => uiBox([
  uiText(String(rank), "sm", lead ? T.onInk : T.ink, { weight: "bold", align: "center" }),
], {
  width: "30px", height: "30px", cornerRadius: "8px", justifyContent: "center", flex: 0,
  backgroundColor: lead ? T.ink : T.slateTint, ...(lead ? { background: { type: "linearGradient", angle: "135deg", startColor: T.headerBackground, endColor: T.headerGradientEnd } } : { borderColor: T.frame, borderWidth: "light" }),
});

/** Title with a short ink rail on its left: marks each item without another framed box. */
export const railTitle = (title: string, sub?: string) => uiBox([
  { type: "box", layout: "vertical", contents: [], width: "4px", backgroundColor: T.ink, cornerRadius: "2px" },
  uiBox([uiText(title, "sm", T.ink, { weight: "bold" }), ...(sub ? [uiText(sub, "xxs", T.subtle)] : [])], { spacing: "none", flex: 1 }),
], { layout: "horizontal", spacing: "md" });

const RAIL = "#B8BEC6";

/** One step of a vertical timeline: a numbered or hollow dot, a rail down to the next step, content on the right. */
export const timelineStep = (marker: string, contents: unknown[], last = false, lead = false) => uiBox([
  uiBox([
    uiBox([uiText(marker, "xxs", lead ? T.onInk : T.ink, { weight: "bold", align: "center" })], {
      width: "22px", height: "22px", cornerRadius: "11px", justifyContent: "center",
      backgroundColor: lead ? T.ink : T.paper, borderColor: T.ink, borderWidth: "medium",
    }),
    ...(last ? [] : [uiBox([{ type: "box", layout: "vertical", contents: [], width: "2px", backgroundColor: RAIL, flex: 1 }],
      { layout: "horizontal", justifyContent: "center", flex: 1 })]),
  ], { width: "22px", flex: 0, spacing: "xs" }),
  uiBox(contents, { flex: 1, spacing: "xs", paddingBottom: last ? "none" : "lg" }),
], { layout: "horizontal", spacing: "md" });

/** Stat tile with an optional meter under the value (for bounded percentages). */
export const statTile = (label: string, value: string, bar?: number, sub?: string) => uiBox([
  uiText(label, "xxs", T.subtle),
  uiText(value, value.length <= 4 ? "xl" : value.length <= 6 ? "lg" : "md", signColor(value), { weight: "bold" }),
  ...(bar === undefined ? [] : [meter(bar)]),
  ...(sub ? [uiText(sub, "xxs", T.subtle)] : []),
], { flex: 1, spacing: "xs", backgroundColor: T.soft, cornerRadius: "md", paddingAll: "md" });

/** Thesis phase ladder: six stages as segments, filled up to the current one, short labels underneath. */
export const PHASE_STEPS = ["DISCOVERY", "EARLY_VALIDATION", "COMMERCIAL_VALIDATION", "INSTITUTIONAL_VALIDATION", "CONSENSUS", "RELIEVING"] as const;
const PHASE_SHORT = ["初現", "驗證", "商業", "法人", "共識", "緩解"];
export const phaseLadder = (phase: string) => {
  const at = PHASE_STEPS.indexOf(phase as typeof PHASE_STEPS[number]);
  return uiBox([
    uiBox(PHASE_STEPS.map((_, index) => ({
      type: "box", layout: "vertical", contents: [], height: "8px", cornerRadius: "4px", flex: 1,
      backgroundColor: phase === "BROKEN" ? T.paleNegative : index < at ? T.strongEnd : index === at ? T.ink : T.border,
    })), { layout: "horizontal", spacing: "xs" }),
    uiBox(PHASE_SHORT.map((label, index) => uiText(label, "xxs", index === at ? T.ink : T.subtle,
      { align: "center", flex: 1, ...(index === at ? { weight: "bold" } : {}) })), { layout: "horizontal", spacing: "xs" }),
  ], { spacing: "xs" });
};

/** Stacked composition bar (for example score weights), shades from ink to pale graphite. */
const SHADES = [T.ink, T.strongEnd, T.subtle, "#8A919B", "#B8BEC6", "#D5D9DF"];
export const stackedBar = (parts: readonly { label: string; weight: number }[]) => {
  const total = parts.reduce((sum, part) => sum + part.weight, 0) || 1;
  return uiBox([
    uiBox(parts.map((part, index) => ({ type: "box", layout: "vertical", contents: [], height: "10px",
      flex: Math.max(1, Math.round((part.weight / total) * 100)), backgroundColor: SHADES[index % SHADES.length] })),
      { layout: "horizontal", spacing: "none", cornerRadius: "5px" }),
    ...Array.from({ length: Math.ceil(parts.length / 3) }, (_, row) => uiBox(parts.slice(row * 3, row * 3 + 3).map((part, offset) => uiBox([
      { type: "box", layout: "vertical", contents: [], width: "8px", height: "8px", cornerRadius: "2px", backgroundColor: SHADES[(row * 3 + offset) % SHADES.length] },
      uiText(`${part.label} ${part.weight}`, "xxs", T.muted, { flex: 1 }),
    ], { layout: "horizontal", spacing: "xs", flex: 1, alignItems: "center" })), { layout: "horizontal", spacing: "sm" })),
  ], { spacing: "sm" });
};

// --- V20 density primitives (additive): one glance = headline number + a few bullets; detail behind a specific button. ---

/** Code-point-safe ellipsis for non-required prose only (never for disclosures, figures or source names). */
export function clampText(text: string, maxChars: number): string {
  const chars = Array.from(text);
  return chars.length <= maxChars ? text : `${chars.slice(0, Math.max(1, maxChars - 1)).join("")}…`;
}

/** Small ink dot that marks a bullet (6px, `flex:0`); the density test recognises bullet rows by it. */
export const BULLET_DOT_SIZE = "6px";
const bulletDot = () => ({ type: "box", layout: "vertical", contents: [], width: BULLET_DOT_SIZE, height: BULLET_DOT_SIZE,
  cornerRadius: "3px", backgroundColor: T.ink, flex: 0, offsetTop: "6px" });

/** One bullet: ink dot plus wrapping text. `maxLines` only for prose whose truncation cannot hide a figure or disclosure. */
export function bulletRow(text: string, options: { size?: string; maxLines?: number; color?: string; weight?: "bold" | "regular" } = {}) {
  const { size = "xs", maxLines, color = T.ink, weight } = options;
  return uiBox([bulletDot(), uiText(text, size, color, { flex: 1, ...(maxLines ? { maxLines } : {}), ...(weight === "bold" ? { weight } : {}) })],
    { layout: "horizontal", spacing: "sm" });
}

/** Specific button: "<verb> <target>" naming what opens; vague labels are rejected. */
/** LINE rejects a message action label over 20 characters. */
export const BUTTON_LABEL_MAX = 20;
const VAGUE_LABELS = new Set(["詳情", "更多", "詳細", "查看", "查看更多", "Details", "More", "details", "more"]);
export function detailsButton(label: string, command: string) {
  if (VAGUE_LABELS.has(label.trim())) throw new Error("V20_BUTTON_LABEL_VAGUE");
  return menuAction(clampText(label, BUTTON_LABEL_MAX), command);
}

/** At most `max` bullets; when more exist a muted "另有 N 項" row (and, if given, a details button) follows. Never use it
 * to drop a required disclosure: disclosures go through `disclosureLine`. */
export function bulletList(items: readonly string[], options: { max?: number; size?: string; maxLines?: number;
  more?: { label: string; command: string } } = {}): unknown[] {
  const { max = 5, size = "xs", maxLines, more } = options;
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  return [
    ...shown.map(item => bulletRow(item, { size, maxLines })),
    ...(rest > 0 ? [uiText(`另有 ${rest} 項`, "xs", T.subtle), ...(more ? [detailsButton(more.label, more.command)] : [])] : []),
  ];
}

/** Label/value row: muted label (`flex:2`), bold right-aligned value (`flex:3`), sign-coloured. Wraps by default (a figure is never cut). */
export function kvRow(label: string, value: string, options: { emphasis?: boolean; maxLines?: number; color?: string; sub?: string } = {}) {
  const { emphasis = false, maxLines, color = signColor(value), sub } = options;
  const row = uiBox([
    uiText(label, "xs", T.subtle, { flex: 2, gravity: "top" }),
    uiText(value, emphasis ? "md" : "sm", color, { flex: 3, align: "end", weight: "bold", ...(maxLines ? { maxLines } : {}) }),
  ], { layout: "horizontal", spacing: "sm" });
  return sub === undefined ? row : uiBox([row, uiText(sub, "xs", T.subtle, { align: "end" })], { spacing: "xs" });
}

/** Label, a bar proportional to value/max, and the displayed value. */
export const barRow = (label: string, value: number, display: string, max = 100) => uiBox([
  uiText(label, "xs", T.subtle, { flex: 2 }),
  uiBox([meter(value, max, T.ink, true)], { flex: 3, justifyContent: "center" }),
  uiText(display, "xs", T.ink, { flex: 2, align: "end", weight: "bold" }),
], { layout: "horizontal", spacing: "sm", alignItems: "center" });

/** ONE xxs line for every required disclosure and source label, parts joined by "｜". Not clamped: the long form of each
 * part stays reachable through a details button. */
export const disclosureLine = (parts: readonly string[]) => uiText(parts.filter(part => part.length > 0).join("｜"), "xxs", T.subtle);

/** The card's headline number: muted label, one large figure, optional sub line. */
export const heroStat = (label: string, value: string, sub?: string, color: string = signColor(value)) => uiBox([
  uiText(label, "xs", T.subtle),
  uiText(value, value.length > 10 ? "xl" : "3xl", color, { weight: "bold" }),
  ...(sub ? [uiText(sub, "xs", T.subtle)] : []),
], { spacing: "xs" });

/** altText "<topic>｜<status>｜<next>" within 120 characters (code-point safe). */
export function altSummary(parts: { topic: string; status: string; next: string }): string {
  return clampText(`${parts.topic}｜${parts.status}｜${parts.next}`, 120);
}

/** Carousels of at most five bubbles and 46 KB each (LINE caps a carousel at 50 KB); validated before return. */
export function packCarousels(bubbles: readonly unknown[], altText: (index: number, total: number) => string): LineOutboundMessage[] {
  const size = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
  const groups: unknown[][] = [];
  for (const bubble of bubbles) {
    const last = groups[groups.length - 1];
    if (last && last.length < 5 && size({ type: "carousel", contents: [...last, bubble] }) <= 46_000) last.push(bubble);
    else groups.push([bubble]);
  }
  const messages: LineOutboundMessage[] = groups.map((contents, index) => ({ type: "flex", altText: altText(index, groups.length),
    contents: { type: "carousel", contents } }));
  assertLineMessages(messages);
  return messages;
}

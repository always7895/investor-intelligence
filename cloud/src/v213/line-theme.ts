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

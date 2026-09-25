/** Investor-report palette: a black-to-graphite gradient identity band, framed
 * sections by information level, and one semantic colour per level.
 * No remote image fetch, new hosting, or claim that a local preview is LINE UI.
 *
 * Design system for LINE Flex surfaces. Text colours meet WCAG AA (4.5:1) on
 * the surface they are used on; sign colours never replace the explicit +/-
 * sign. Sizes are LINE keywords only (no px), so layouts scale with the client.
 */
export const LINE_THEME = Object.freeze({ ink: "#111827", muted: "#4B5563", paper: "#FFFFFF",
  green: "#147D47", paleGreen: "#ECF6F0", border: "#E4E7EB", soft: "#F5F6F8",
  // Operator direction 2026-09-25: coloured top band, framed sections per level,
  // investor-readable (warm and plain variants rejected).
  subtle: "#5F6773", frame: "#D8DEE4",
  headerBackground: "#0A0A0B", headerGradientEnd: "#2D3139",
  headerText: "#FFFFFF", headerMuted: "#D1D5DB", headerSubtle: "#A7AFBA", headerAlert: "#FCA5A5",
  slateTint: "#F1F3F6", slateTitle: "#374151", amberTint: "#FFF7E6", amberTitle: "#92400E",
  onAccent: "#FFFFFF", onInk: "#FFFFFF",
  negative: "#B42318", paleNegative: "#FEF3F2", caution: "#9A3412", paleCaution: "#FFF7ED" });

export const menuText = (text: string, size = "sm", color: string = LINE_THEME.ink) => ({ type: "text", text, size, color, wrap: true });
export const menuBox = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", spacing: "md", contents, ...extra });
/** Shared action contract: every product button is a link-style, md-height (mobile tap target), brand-green button. */
export const menuAction = (label: string, command: string) => ({ type: "button", style: "link", height: "md", color: LINE_THEME.green,
  action: { type: "message", label, text: command } });

const T = LINE_THEME;

/** Black-to-graphite gradient behind every product header; the solid colour is the fallback. */
export const headerGradient = Object.freeze({ type: "linearGradient", angle: "135deg", startColor: T.headerBackground, endColor: T.headerGradientEnd });

/** Box style shared by every product header: the dark identity band. */
export const headerStyle = Object.freeze({ backgroundColor: T.headerBackground, background: headerGradient, paddingAll: "xl" });

/** Sign-aware value colour; the sign itself stays in the text. */
export function signColor(value: string): string {
  const trimmed = value.trim();
  if (/^\+\d/.test(trimmed)) return T.green;
  if (/^[-−]\d/.test(trimmed)) return T.negative;
  return /^\d/.test(trimmed) ? T.ink : T.subtle;
}

export const uiText = (text: string, size = "sm", color: string = T.ink, extra: Record<string, unknown> = {}) =>
  ({ type: "text", text, size, color, wrap: true, ...extra });

export const uiBox = (contents: unknown[], extra: Record<string, unknown> = {}) =>
  ({ type: "box", layout: "vertical", spacing: "sm", contents, ...extra });

/** Rounded pill label (rank, status); brand green with white text reads clearly on the dark band. */
export const chip = (text: string, backgroundColor: string = T.green, color: string = T.onAccent) =>
  uiBox([uiText(text, "xxs", color, { weight: "bold", align: "center" })], {
    backgroundColor, cornerRadius: "xxl", paddingStart: "md", paddingEnd: "md", paddingTop: "xs", paddingBottom: "xs",
    flex: 0, justifyContent: "center",
  });

/** Small heading in the brand accent (used outside framed sections). */
export const sectionTitle = (text: string, color: string = T.green) => uiText(text, "xxs", color, { weight: "bold" });

/** Label immediately followed by its value (seven-field inspectors rely on this order). */
export const labelValue = (label: string, value: string, valueExtra: Record<string, unknown> = {}, flex = 1) =>
  uiBox([uiText(label, "xxs", T.subtle), uiText(value, "sm", T.ink, valueExtra)], { flex, spacing: "xs" });

/** KPI tile: muted label, large sign-coloured value. Long values step down in size. */
export const kpiTile = (label: string, value: string, color: string = signColor(value)) => uiBox([
  uiText(label, "xxs", T.subtle),
  uiText(value, value.length > 8 ? "sm" : "xl", color, { weight: "bold" }),
], { flex: 1, spacing: "xs", backgroundColor: T.soft, cornerRadius: "md", paddingAll: "md" });

const SECTION_TONES = Object.freeze({
  green: [T.paleGreen, T.green], slate: [T.slateTint, T.slateTitle], amber: [T.amberTint, T.amberTitle],
} as const);

/** Framed section: a tinted title strip names the information level, content sits below. */
export const section = (title: string, contents: unknown[], tone: keyof typeof SECTION_TONES = "slate") => {
  const [tint, titleColor] = SECTION_TONES[tone];
  return uiBox([
    uiBox([uiText(title, "sm", titleColor, { weight: "bold" })], {
      backgroundColor: tint, paddingStart: "md", paddingEnd: "md", paddingTop: "sm", paddingBottom: "sm",
    }),
    uiBox(contents, { paddingAll: "md", spacing: "md" }),
  ], { borderColor: T.frame, borderWidth: "light", cornerRadius: "md", spacing: "none" });
};

/** Callout panel for warnings and notes. */
export const panel = (contents: unknown[], tone: "green" | "neutral" | "caution" = "neutral") => uiBox(contents, {
  backgroundColor: tone === "green" ? T.paleGreen : tone === "caution" ? T.paleCaution : T.paper,
  borderColor: tone === "green" ? "#B7DFC5" : tone === "caution" ? "#FED7AA" : T.border,
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

/** High-contrast monochrome + green accents from the operator's mascot artwork.
 * No remote image fetch, new hosting, or claim that a local preview is LINE UI.
 *
 * Design system for LINE Flex surfaces. Text colours meet WCAG AA (4.5:1) on
 * the surface they are used on; sign colours never replace the explicit +/-
 * sign. Sizes are LINE keywords only (no px), so layouts scale with the client.
 */
export const LINE_THEME = Object.freeze({ ink: "#171717", muted: "#525252", paper: "#FFFFFF",
  green: "#147D47", paleGreen: "#EDF8F0", border: "#E5E5E5", soft: "#F5F5F5",
  // Added tokens (existing keys above keep their values for current callers).
  subtle: "#6B6B6B", deepGreen: "#0E3B24", night: "#121212",
  onDark: "#FFFFFF", onDarkMuted: "#D4D4D4", onDarkSubtle: "#A3A3A3",
  negative: "#B42318", paleNegative: "#FEF3F2", caution: "#9A3412", paleCaution: "#FFF7ED",
  onDarkAlert: "#FCA5A5" });

export const menuText = (text: string, size = "sm", color: string = LINE_THEME.ink) => ({ type: "text", text, size, color, wrap: true });
export const menuBox = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", spacing: "md", contents, ...extra });
/** Shared action contract: every product button is a link-style, md-height (mobile tap target), brand-green button. */
export const menuAction = (label: string, command: string) => ({ type: "button", style: "link", height: "md", color: LINE_THEME.green,
  action: { type: "message", label, text: command } });

const T = LINE_THEME;

/** Deep ink-to-green gradient used by every product header. */
export const headerBackground = Object.freeze({ type: "linearGradient", angle: "135deg", startColor: T.night, endColor: T.deepGreen });

/** Box style shared by every product header (gradient, solid fallback, generous padding). */
export const headerStyle = Object.freeze({ backgroundColor: T.night, background: headerBackground, paddingAll: "xl" });

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

/** Rounded pill label (rank, status). */
export const chip = (text: string, backgroundColor: string = T.green, color: string = T.onDark) =>
  uiBox([uiText(text, "xxs", color, { weight: "bold", align: "center" })], {
    backgroundColor, cornerRadius: "xxl", paddingStart: "md", paddingEnd: "md", paddingTop: "xs", paddingBottom: "xs",
    flex: 0, justifyContent: "center",
  });

/** Small uppercase-style section heading with a brand accent. */
export const sectionTitle = (text: string, color: string = T.green) => uiText(text, "xxs", color, { weight: "bold" });

/** Label immediately followed by its value (seven-field inspectors rely on this order). */
export const labelValue = (label: string, value: string, valueExtra: Record<string, unknown> = {}, flex = 1) =>
  uiBox([uiText(label, "xxs", T.subtle), uiText(value, "sm", T.ink, valueExtra)], { flex, spacing: "xs" });

/** KPI tile: muted label, large sign-coloured value. Long values step down in size. */
export const kpiTile = (label: string, value: string, color: string = signColor(value)) => uiBox([
  uiText(label, "xxs", T.subtle),
  uiText(value, value.length > 8 ? "sm" : "xl", color, { weight: "bold" }),
], { flex: 1, spacing: "xs", backgroundColor: T.soft, cornerRadius: "lg", paddingAll: "md" });

/** Bordered callout panel; tone switches the tint without changing structure. */
export const panel = (contents: unknown[], tone: "green" | "neutral" | "caution" = "neutral") => uiBox(contents, {
  backgroundColor: tone === "green" ? T.paleGreen : tone === "caution" ? T.paleCaution : T.paper,
  borderColor: tone === "green" ? "#B7DFC5" : tone === "caution" ? "#FED7AA" : T.border,
  borderWidth: "light", cornerRadius: "lg", paddingAll: "md", spacing: "md",
});

export const divider = () => ({ type: "separator", color: T.border });


/** Shared product header: gradient with a solid fallback, eyebrow line and bold title. */
export const productHeader = (eyebrow: string, title: string, extra: unknown[] = []) => uiBox([
  uiText(eyebrow, "xxs", T.onDarkMuted, { weight: "bold" }),
  uiText(title, "xl", T.onDark, { weight: "bold" }),
  ...extra,
], { backgroundColor: T.night, background: headerBackground, paddingAll: "xl", spacing: "sm" });

/** Compact footnote text for disclosures that must remain visible. */
export const footnote = (text: string) => uiText(text, "xxs", T.subtle);

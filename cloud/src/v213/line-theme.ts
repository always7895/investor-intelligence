/** High-contrast monochrome + green accents from the operator's mascot artwork.
 * No remote image fetch, new hosting, or claim that a local preview is LINE UI.
 */
export const LINE_THEME = Object.freeze({ ink: "#171717", muted: "#525252", paper: "#FFFFFF",
  green: "#147D47", paleGreen: "#EDF8F0", border: "#E5E5E5", soft: "#F5F5F5" });
export const menuText = (text: string, size = "sm", color: string = LINE_THEME.ink) => ({ type: "text", text, size, color, wrap: true });
export const menuBox = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", spacing: "md", contents, ...extra });
export const menuAction = (label: string, command: string) => ({ type: "button", style: "link", height: "sm", color: LINE_THEME.green,
  action: { type: "message", label, text: command } });

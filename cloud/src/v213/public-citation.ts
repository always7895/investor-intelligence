/** URL-shape admission only; not a DNS, source-authority or redistribution check. */
export function isPublicCitationUrl(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 1000 || !value.startsWith("https://") || /[\\\s\u0000-\u001f\u007f]/.test(value)) return false;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) return false;
    if (!/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*$/i.test(url.hostname) || /\.(?:local|localhost|internal|lan|localdomain)$/i.test(url.hostname)) return false;
    let decoded = value;
    for (let depth = 0; depth < 4; depth++) {
      if (/[\u0000-\u001f\u007f]/.test(decoded)) return false;
      // Inspect bounded parameter names without a backtracking catch-all regex.
      for (const part of decoded.split(/[?&#;]/)) {
        const equals = part.indexOf("=");
        if (equals < 0) continue;
        const key = part.slice(0, equals);
        if (/(?:token|api[_-]?key|authorization|password|secret|signature|credential|session|cookie|jwt)/i.test(key) || /^(?:auth|key|sig)$/i.test(key)) return false;
      }
      // Decode encoded runs, not a literal percent produced by an earlier pass.
      // This preserves legitimate filenames such as growth100%25.pdf.
      if (depth === 0 && /%(?![0-9a-f]{2})/i.test(decoded)) return false;
      const next = decoded.replace(/(?:%[0-9a-f]{2})+/gi, part => decodeURIComponent(part));
      if (next === decoded) return true;
      decoded = next;
    }
    // Ambiguous/deeply encoded forms are not accepted as public citations.
    return false;
  } catch { return false; }
}

export function requirePublicCitation(value: string): string {
  if (!isPublicCitationUrl(value)) throw new Error("UNSAFE_REPORT_CITATION");
  return value;
}

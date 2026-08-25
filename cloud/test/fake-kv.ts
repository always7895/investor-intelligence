export class MemoryKv {
  values = new Map<string, string>();

  async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
    const value = this.values.get(key);
    if (value === undefined) return null;
    if (type === "json") return JSON.parse(value) as T;
    return value;
  }

  async put(key: string, value: string | ArrayBuffer | ArrayBufferView): Promise<void> {
    if (typeof value === "string") {
      this.values.set(key, value);
      return;
    }
    const bytes = value instanceof ArrayBuffer
      ? new Uint8Array(value)
      : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    this.values.set(key, new TextDecoder().decode(bytes));
  }

  async delete(key: string): Promise<void> {
    this.values.delete(key);
  }

  async list(options: { prefix?: string; cursor?: string } = {}): Promise<{
    keys: Array<{ name: string }>;
    list_complete: boolean;
    cursor: string;
  }> {
    const prefix = options.prefix ?? "";
    return {
      keys: [...this.values.keys()]
        .filter((key) => key.startsWith(prefix))
        .map((name) => ({ name })),
      list_complete: true,
      cursor: "",
    };
  }
}

export function asKv(value: MemoryKv): KVNamespace {
  return value as unknown as KVNamespace;
}

import '@testing-library/jest-dom'

// Node versions launched with an invalid --localstorage-file can expose a
// placeholder localStorage object without the Web Storage methods. Keep the
// tests deterministic in that environment while preserving jsdom's native
// implementation everywhere else.
if (typeof window.localStorage?.getItem !== 'function') {
  const values = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, String(value)),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size },
    },
  })
}

// jsdom does not implement scrollIntoView. Stubbed here rather than guarded in
// the components: keeping a chat scrolled to the newest message is real
// behaviour, and a component that checked for the method's existence would be
// carrying test-environment knowledge in product code.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

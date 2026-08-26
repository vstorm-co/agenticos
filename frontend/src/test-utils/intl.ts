/**
 * A key-as-value `useTranslations` for tests, carrying the members the real `t`
 * has.
 *
 * Local `next-intl` mocks return keys instead of copy so assertions can name a
 * message rather than its English. A bare `(key) => key` is not `t`, though: `t`
 * carries `t.rich`, `t.markup` and `t.has`, and a component reading a message
 * with a tag calls `t.rich`. A bare mock throws `t.rich is not a function`
 * inside a component several files from the assertion, in a spec about something
 * else (#612). One definition here keeps every local mock complete.
 *
 * `format` preserves each caller's existing key shape - `(key) => key`, or
 * `(ns, key) => ns.key` - so no assertion moves.
 */
export function keyTranslations(
  format: (namespace: string | undefined, key: string) => string = (_namespace, key) => key,
) {
  return (namespace?: string) => {
    const translate = (key: string) => format(namespace, key);
    return Object.assign(translate, {
      rich: (key: string) => format(namespace, key),
      markup: (key: string) => format(namespace, key),
      has: (_key: string) => true,
    });
  };
}

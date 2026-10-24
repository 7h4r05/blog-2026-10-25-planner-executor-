export function log(
  message: string,
  data?: unknown
): void {
  const timestamp =
    new Date().toISOString();

  const suffix =
    data === undefined
      ? ""
      : ` ${JSON.stringify(data)}`;

  process.stderr.write(
    `[${timestamp}] ${message}${suffix}\n`
  );
}

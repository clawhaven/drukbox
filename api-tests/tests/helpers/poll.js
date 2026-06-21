async function pollUntil(fn, options = {}) {
  const timeoutMs = options.timeoutMs ?? 120_000;
  const intervalMs = options.intervalMs ?? 2_000;
  const message = options.message ?? "condition was not met";
  const deadline = Date.now() + timeoutMs;
  let lastValue;

  while (Date.now() < deadline) {
    lastValue = await fn();

    if (lastValue) {
      return lastValue;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`${message}. Last value: ${JSON.stringify(lastValue)}`);
}

module.exports = { pollUntil };

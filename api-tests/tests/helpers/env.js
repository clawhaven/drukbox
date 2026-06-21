function requiredEnv(name) {
  const value = process.env[name];

  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function positiveNumberEnv(name, defaultValue) {
  const rawValue = process.env[name] || String(defaultValue);
  const value = Number(rawValue);

  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a positive number`);
  }
  return value;
}

function settings() {
  const hostImage = process.env.HOST_IMAGE || undefined;
  const expectedProvider = process.env.DEFAULT_HOST_PROVIDER || "exe";
  const providerDefaultImage =
    process.env[`${expectedProvider.toUpperCase()}_DEFAULT_IMAGE`] || undefined;

  return {
    baseURL: requiredEnv("SERVICE_URL").replace(/\/+$/, ""),
    serviceToken: requiredEnv("SERVICE_TOKEN"),
    requestTimeoutMs: positiveNumberEnv("API_TIMEOUT_MS", 30_000),
    hostActiveTimeoutMs: positiveNumberEnv("HOST_ACTIVE_TIMEOUT_MS", 600_000),
    hostPollIntervalMs: positiveNumberEnv("HOST_POLL_INTERVAL_MS", 5_000),
    hostImage,
    expectedHostImage: hostImage || providerDefaultImage,
    expectedProvider,
  };
}

module.exports = { settings };

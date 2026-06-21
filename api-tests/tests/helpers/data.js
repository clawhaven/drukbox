function hostEnv() {
  return {
    SKIP_GATEWAY_HEALTH_CHECK: process.env.SKIP_GATEWAY_HEALTH_CHECK || "true",
    TAILSCALE_ADVERTISE_TAGS: process.env.TAILSCALE_ADVERTISE_TAGS || "tag:sandbox",
  };
}

module.exports = {
  hostEnv,
};

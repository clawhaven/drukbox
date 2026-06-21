const { request } = require("@playwright/test");
const { settings } = require("./env");

function jsonHeaders(token) {
  const headers = {
    Accept: "application/json",
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function newServiceContext(token) {
  const config = settings();

  return request.newContext({
    baseURL: config.baseURL,
    extraHTTPHeaders: jsonHeaders(token ?? config.serviceToken),
    ignoreHTTPSErrors: true,
    timeout: config.requestTimeoutMs,
  });
}

async function newPublicContext() {
  const config = settings();

  return request.newContext({
    baseURL: config.baseURL,
    extraHTTPHeaders: jsonHeaders(),
    ignoreHTTPSErrors: true,
    timeout: config.requestTimeoutMs,
  });
}

module.exports = {
  newPublicContext,
  newServiceContext,
};

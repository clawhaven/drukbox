const { expect } = require("@playwright/test");

async function expectJson(response, status) {
  expect(response.status(), await response.text()).toBe(status);
  return response.json();
}

async function expectStatus(response, status) {
  expect(response.status(), await response.text()).toBe(status);
}

function expectObject(value, keys) {
  expect(value).toBeTruthy();
  expect(typeof value).toBe("object");
  expect(Array.isArray(value)).toBe(false);

  for (const key of keys) {
    expect(value, `expected object to include ${key}`).toHaveProperty(key);
  }
}

module.exports = {
  expectJson,
  expectObject,
  expectStatus,
};

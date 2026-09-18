"use strict";

function finitePrice(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function providerSnapshot(offer, providerId) {
  const source = offer?.prices?.[providerId] || {};
  const price = finitePrice(source.price);
  return {
    price,
    available: source.available === true && price !== null,
    status: String(source.status || ""),
    status_text: String(source.status_text || ""),
  };
}

function collectProviderChanges(before, current, providerIds = []) {
  const changes = [];
  for (const providerId of providerIds) {
    const oldSnapshot = providerSnapshot(before, providerId);
    const newSnapshot = providerSnapshot(current, providerId);

    if (oldSnapshot.price !== null && newSnapshot.price !== null) {
      if (oldSnapshot.price !== newSnapshot.price) {
        changes.push({
          type: "price",
          providerId,
          oldPrice: oldSnapshot.price,
          newPrice: newSnapshot.price,
          difference: newSnapshot.price - oldSnapshot.price,
          oldStatus: oldSnapshot.status,
          newStatus: newSnapshot.status,
        });
      }
      continue;
    }

    if (oldSnapshot.price === null && newSnapshot.price !== null && newSnapshot.available) {
      changes.push({
        type: "available",
        providerId,
        oldPrice: null,
        newPrice: newSnapshot.price,
        difference: null,
        oldStatus: oldSnapshot.status,
        newStatus: newSnapshot.status,
      });
      continue;
    }

    // Bei einem technischen Prüfproblem (provider_unverified) keine
    // "nicht mehr verfügbar"-Meldung erzeugen. Das verhindert Fehlalarme.
    if (
      oldSnapshot.price !== null &&
      newSnapshot.price === null &&
      ["not_offered", "unavailable"].includes(newSnapshot.status)
    ) {
      changes.push({
        type: "unavailable",
        providerId,
        oldPrice: oldSnapshot.price,
        newPrice: null,
        difference: null,
        oldStatus: oldSnapshot.status,
        newStatus: newSnapshot.status,
      });
    }
  }
  return changes;
}

module.exports = {
  collectProviderChanges,
  providerSnapshot,
};

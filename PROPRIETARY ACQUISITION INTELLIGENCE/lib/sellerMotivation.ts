import type { Listing, SellerMotivation } from "./types";
import { clamp } from "./format";

const URGENCY_PHRASES = [
  "must sell",
  "motivated seller",
  "retiring",
  "retirement",
  "health",
  "relocating",
  "priced to sell",
  "urgent",
  "bring all offers",
  "owner financing",
  "quick sale",
];

export function analyzeSellerMotivation(listing: Listing): SellerMotivation {
  const signals: string[] = [];
  let score = 25; // base

  // Days on market — staleness is the strongest signal
  if (listing.daysOnMarket > 270) {
    score += 25;
    signals.push(`Listed ${listing.daysOnMarket} days — well past the ~180-day norm (stale).`);
  } else if (listing.daysOnMarket > 150) {
    score += 15;
    signals.push(`On market ${listing.daysOnMarket} days — approaching stale.`);
  } else if (listing.daysOnMarket < 30) {
    score -= 5;
    signals.push(`Fresh listing (${listing.daysOnMarket} days) — seller less likely to flex yet.`);
  }

  // Price reductions
  if (listing.priceReductions >= 2) {
    score += 20;
    signals.push(`${listing.priceReductions} price cuts already — clear willingness to move.`);
  } else if (listing.priceReductions === 1) {
    score += 10;
    signals.push("One prior price reduction on record.");
  }

  const cutPct =
    listing.originalAskingPrice > 0
      ? ((listing.originalAskingPrice - listing.askingPrice) / listing.originalAskingPrice) * 100
      : 0;
  if (cutPct >= 10) {
    score += 8;
    signals.push(`Asking is down ${cutPct.toFixed(0)}% from the original list price.`);
  }

  // Seller financing offered = motivation + flexibility
  if (listing.sellerFinancingAvailable) {
    score += 10;
    signals.push(`Seller will carry ~${listing.sellerFinancingPct}% — strong flexibility signal.`);
  }

  // Absentee owners are often less emotionally attached
  if (listing.ownerInvolvement === "absentee") {
    score += 6;
    signals.push("Absentee owner — typically more transactional, less attached.");
  }

  // Reason-for-sale + description language scan
  const text = `${listing.reasonForSale} ${listing.description}`.toLowerCase();
  const hits = URGENCY_PHRASES.filter((p) => text.includes(p));
  if (hits.length > 0) {
    score += Math.min(12, hits.length * 4);
    signals.push(`Urgency language detected: "${hits.slice(0, 3).join('", "')}".`);
  }

  score = clamp(score);

  const level: SellerMotivation["level"] =
    score >= 75 ? "Very High" : score >= 55 ? "High" : score >= 35 ? "Moderate" : "Low";

  // Negotiation room grows with motivation
  const negotiationRoomPct = Math.round(clamp(score * 0.28, 3, 28));
  const suggestedOpeningOfferPct = clamp(100 - negotiationRoomPct - 6, 60, 95);

  let strategy: string;
  if (score >= 75) {
    strategy =
      "Lead with a firm, well-below-ask offer backed by proof of funds and a fast close. Seller pain is high — anchor low and use time pressure.";
  } else if (score >= 55) {
    strategy =
      "Open moderately below ask, emphasize certainty of close and clean SBA financing. Ask the seller to carry a note to bridge any valuation gap.";
  } else if (score >= 35) {
    strategy =
      "Compete on terms, not just price. A slightly-under-ask offer with a strong earnest deposit and short diligence window will resonate more than a lowball.";
  } else {
    strategy =
      "Little leverage today. Submit a fair offer or set a watch alert — motivation typically rises after 120+ days or a first price cut.";
  }

  return {
    score,
    level,
    negotiationRoomPct,
    suggestedOpeningOfferPct: Math.round(suggestedOpeningOfferPct),
    signals,
    strategy,
  };
}

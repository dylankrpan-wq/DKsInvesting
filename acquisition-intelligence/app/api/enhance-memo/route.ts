import Anthropic from "@anthropic-ai/sdk";

// Opt-in Claude enhancement of the deterministic investment memo.
// Runs only when ANTHROPIC_API_KEY is set; otherwise returns a friendly notice
// so the Due Diligence page degrades gracefully with no key configured.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return Response.json({
      enhanced: null,
      reason:
        "Claude enhancement is off. Set ANTHROPIC_API_KEY in your environment (e.g. a .env.local file) and restart to enable it.",
    });
  }

  let memo = "";
  let name = "the business";
  try {
    const body = await req.json();
    memo = String(body?.memo ?? "");
    if (body?.name) name = String(body.name);
  } catch {
    return Response.json({ enhanced: null, reason: "Invalid request body." }, { status: 400 });
  }
  if (!memo.trim()) {
    return Response.json({ enhanced: null, reason: "No memo supplied." }, { status: 400 });
  }

  const client = new Anthropic({ apiKey });

  try {
    const response = await client.messages.create({
      model: "claude-opus-4-8",
      max_tokens: 4000,
      system:
        "You are a lower-middle-market M&A analyst writing for an investment committee. " +
        "Rewrite the provided screening memo into a polished, well-structured investment memo with these sections: " +
        "Overview, Investment Thesis, Financial Highlights, Financing, Key Risks & Mitigants, Valuation, and Recommendation. " +
        "Preserve every figure exactly as given — do not invent numbers. Be concise, direct, and decision-oriented. " +
        "Return clean prose with clear section headers; no preamble.",
      messages: [
        {
          role: "user",
          content: `Rewrite this screening memo for ${name} into a committee-ready investment memo:\n\n${memo}`,
        },
      ],
    });

    const text = response.content
      .filter((b): b is Anthropic.TextBlock => b.type === "text")
      .map((b) => b.text)
      .join("\n")
      .trim();

    return Response.json({ enhanced: text || null, model: response.model });
  } catch (err) {
    const message =
      err instanceof Anthropic.APIError ? `${err.status ?? ""} ${err.message}`.trim() : "Enhancement request failed.";
    return Response.json({ enhanced: null, reason: message }, { status: 200 });
  }
}

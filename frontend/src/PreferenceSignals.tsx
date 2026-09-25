import type { Decision } from "./types";

/** Provider output types stay visible: LLM categories are not probabilities. */
export default function PreferenceSignals({
  decision,
}: {
  decision: Pick<Decision, "mode" | "preference_scores">;
}) {
  if (!decision.preference_scores.length) return null;
  const categorical = decision.mode !== "jev";
  return (
    <div className="preference-signals">
      <div className="section-title">
        <span>Research preferences</span>
        <span className="tiny">
          {decision.mode === "jev"
            ? "JEV MODEL SIGNALS"
            : decision.mode === "llm"
              ? "CATEGORICAL ANSWERS"
              : "NOT EVALUATED"}
        </span>
      </div>
      {decision.preference_scores.map((preference) => {
        const category =
          decision.mode !== "llm"
            ? "Unknown"
            : preference.value === 1
              ? "Supported"
              : preference.value === 0
                ? "Not established"
                : "Unknown";
        return (
          <div
            className={`signal-row ${categorical ? "categorical" : ""}`}
            key={preference.id}
          >
            <span>{preference.label}</span>
            {!categorical && (
              <div className="signal-track" aria-hidden="true">
                <span style={{ width: `${(preference.value ?? 0) * 100}%` }} />
              </div>
            )}
            <strong
              title={
                categorical
                  ? "Whether the abstract establishes this preference; not a probability."
                  : "Model affirmative probability, not calibrated correctness."
              }
            >
              {categorical
                ? category
                : preference.value === null
                  ? "Unknown"
                  : `${Math.round(preference.value * 100)}%`}
            </strong>
          </div>
        );
      })}
    </div>
  );
}

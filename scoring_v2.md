# FlightBench — Simplified Landing Score V2

Redesign FlightBench's landing score to reward **accurate, stable, smooth and safe landings**, using a simple Total Flight Error formula.

Avoid overengineering. Use existing JSBSim telemetry and a small number of understandable metrics.

## 1. Main formula

\[
\boxed{
S=100\cdot G_{\text{success}}\cdot e^{-E}
}
\]

Where:

- \(S\): Final score (0–100).
- \(G_{\text{success}}\): 1 for a successful landing and rollout; otherwise 0.
- \(E\): Total normalized flight error.

Calculate:

\[
\boxed{
E=0.30E_{\text{lateral}}
+0.25E_{\text{pitch}}
+0.20E_{\text{glide}}
+0.25E_{\text{touchdown}}
}
\]

All four errors must be nonnegative and dimensionless.

## 2. Lateral error — 30%

Penalize deviation from the runway centerline throughout the approach.

\[
E_{\text{lateral}}=
\frac{1}{T_{\text{ref}}}
\int_0^{T_{\text{TD}}}
\left(\frac{z(t)}{10}\right)^2dt
\]

Where `z(t)` is the lateral centerline offset in meters.

A controller that flies away from the centerline for a long time should be penalized even if it corrects its position at the end.

Use `runway.centerline_offset_m`, not the deadbanded cross-track error.

## 3. Pitch stability error — 25%

Penalize excessive pitch attitude and abrupt nose-up/nose-down movements throughout the approach, while allowing a natural and realistic landing flare.

\[
E_{\text{pitch}}=
\frac{1}{T_{\text{ref}}}
\int_0^{T_{\text{TD}}}
\left[
0.7\left(\frac{\max(0,|\theta(t)|-\theta_{\text{limit}}(t))}{10}\right)^2+
0.3\left(\frac{q(t)}{10}\right)^2
\right]dt
\]

Where:

- \(\theta(t)\): Pitch angle in degrees.
- \(q(t)\): Pitch angular velocity in degrees/second.
- \(\theta_{\text{limit}}(t)\): Phase-dependent allowable pitch angle, in degrees.

**Determine the appropriate pitch limits yourself instead of using a fixed 8° threshold.**

Investigate the existing C172x aircraft model, its flight dynamics, normal approach attitude, and realistic landing flare behavior.

Establish a simple, physically reasonable pitch tolerance that:

- Uses an appropriate pitch limit during normal approach.
- Allows a somewhat higher nose-up pitch during the final flare.
- Penalizes excessive nose-up or nose-down attitudes.
- Distinguishes a natural, controlled flare from an exaggerated nose-up maneuver.
- Does not reward abrupt pitch oscillations or aggressive corrections.

Prefer a simple altitude-dependent or flight-phase-dependent threshold rather than introducing complex flare detection systems.

Determine and justify the threshold values using aircraft characteristics, relevant aviation references, and representative simulated landings. Keep the limits configurable.

Also verify that the pitch-rate normalization of 10°/s is reasonable; adjust it if necessary.

The primary goal is to prevent controllers from obtaining high scores by excessively raising the nose immediately before touchdown, without unfairly penalizing proper landing technique.

## 4. Glidepath error — 20%

Penalize deviation from the expected approach glidepath.

\[
E_{\text{glide}}=
\frac{1}{T_{\text{ref}}}
\int_0^{T_{\text{TD}}}
\left(\frac{e_h(t)}{15}\right)^2dt
\]

Where:

\[
e_h(t)=h(t)-h_{\text{target}}(t)
\]

Use the existing 3° glidepath as the target during approach.

Stop accumulating this error during the final flare to avoid penalizing normal landing behavior. A simple altitude threshold may be used.

## 5. Touchdown error — 25%

Evaluate touchdown using existing measurements:

\[
E_{\text{touchdown}}=
0.50\left(\frac{|v_{\text{sink}}|}{3}\right)^2+
0.25\left(\frac{|z_{\text{TD}}|}{15}\right)^2+
0.25\left(\frac{|x_{\text{TD}}-200|}{200}\right)^2
\]

Where:

- \(v_{\text{sink}}\): Touchdown vertical speed (m/s).
- \(z_{\text{TD}}\): Lateral touchdown position (m).
- \(x_{\text{TD}}\): Longitudinal touchdown position (m).

The longitudinal target of 200 m is an initial scoring reference, not a universal ideal touchdown point.

Keep the existing touchdown safety checks and successful rollout requirement.

## 6. Important requirements

- Use the existing JSBSim observations.
- Integrate trajectory errors using simulation time, not API-call frequency.
- Use a fixed reference duration `T_ref` for comparable scores.
- Do not allow a longer flight to dilute accumulated errors.
- Calculate trajectory errors only until first main-gear touchdown.
- Keep the existing safety and landing-success conditions.
- Use the exponential formula to map total error to a score between 0 and 100.
- Keep numerical calculations deterministic.
- Exclude API latency, costs and decision counts from the score.
- Preserve the previous scoring formula as V1 and identify the new formula as V2.
- Make normalization constants configurable, but do not add unnecessary complexity.

## 7. Expected behavior

The new formula should satisfy these comparisons:

| Flight A | Flight B | Expected |
|---|---|---|
| Stable centerline approach | Large lateral oscillations | A scores higher |
| Controlled pitch with natural flare | Excessive nose-up before touchdown | A scores higher |
| Stable descent | Repeated climb/descent corrections | A scores higher |
| Controlled touchdown | Hard touchdown | A scores higher |
| Successful landing | Runway excursion or crash | Successful landing scores higher |

## Final instruction

Implement this simplified scoring formula in the existing FlightBench project.

Keep the implementation compact and understandable.

Do not introduce complex flight-phase detection, passenger acceleration models, jerk calculations, additional simulation systems, or unnecessary abstractions.

**The primary goal is to reward accurate runway tracking, controlled nose attitude, stable descent and safe touchdown throughout the entire landing.**

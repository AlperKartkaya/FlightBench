#set page(width: 900pt, height: auto, margin: 28pt, fill: white)
#set text(font: "Libertinus Serif", size: 14pt, fill: rgb("182235"))
#set par(leading: .65em)
#align(center)[
  #text(size: 25pt, weight: "bold")[FlightBench · Landing score V2]
  #v(8pt)
  $ S = 100 G_"success" exp(-E) $
  $ E = 0.30 E_"lateral" + 0.25 E_"pitch" + 0.20 E_"glide" + 0.25 E_"touchdown" $
]
#v(8pt)
#grid(columns: (1fr, 1fr), gutter: 22pt,
[
*Lateral tracking · 30%*
$ E_"lateral" = 1/T_"ref" integral_0^(T_"TD") (z(t)/10)^2 dif t $
*Pitch stability · 25%*
$ E_"pitch" = 1/T_"ref" integral_0^(T_"TD") [0.7 (max(0, abs(theta(t)) - theta_"lim"(t))/10)^2 + 0.3 (q(t)/10)^2] dif t $
], [
*Glidepath · 20%*
$ E_"glide" = 1/T_"ref" integral_0^(T_"TD") bb(1)_(h(t)>6) ((h(t)-h_"target"(t))/15)^2 dif t $
*Touchdown · 25%*
$ E_"touchdown" = 0.50 (abs(v_"sink")/3)^2 + 0.25 (abs(z_"TD")/15)^2 + 0.25 (abs(x_"TD"-200)/200)^2 $
])
#line(length: 100%, stroke: .6pt + rgb("bdc8d6"))
*Definitions and units*

$G_"success"=1$ only after safe touchdown and completed rollout; otherwise $0$.
$T_"ref"=60$ s is fixed; $T_"TD"$ is first main-gear contact. Longer flights cannot dilute error.

$z$: actual centerline offset (m). $theta$: pitch (degrees). $q$: pitch rate (degrees/s).
$theta_"lim"=6 degree$ above 6 m AGL; $10 degree$ at or below 6 m for the flare.

$h$: altitude AGL (m). $h_"target"=15+d tan(3 degree)$, with $d$ the signed distance before the threshold (m).
Glide error is accumulated only above 6 m AGL. $v_"sink"$: touchdown vertical speed (m/s).
$x_"TD"$: distance along runway (m); $z_"TD"$: lateral touchdown offset (m).

*Integration:* every 120 Hz physics step, until first main-gear touchdown. All four errors are dimensionless and nonnegative. API delay, tokens, cost and decision count do not enter the score.

#text(size: 11pt, fill: rgb("54657b"))[Pitch limits are configurable benchmark tolerances, not certified flight limits. V2 has no 50-point success threshold: use the recorded success flag.]

#set page(width: 900pt, height: auto, margin: 28pt, fill: white)
#set text(font: "Libertinus Serif", size: 14pt, fill: rgb("182235"))
#set par(leading: .6em)
#align(center)[
  #text(size: 24pt, weight: "bold")[Previous score · V1 · touchdown only]
  $ Q = 25 u_"zone" + 20 u_"center" + 25 u_"sink" + 10 u_"heading" + 10 u_"bank" + 10 u_"speed" $
  $ S_1 = cases(max(50,Q) & "if landing and rollout succeeded", min(49,Q) & "otherwise") $
]
With $[a]_+ = max(0,a)$, the default components were:
$ u_"zone" = [1 - max(50-x,0,x-350)/300]_+ quad u_"center" = [1 - abs(z)/15]_+ $
$ u_"sink" = [1 - abs(v_"sink")/3]_+ quad u_"heading" = [1 - abs(psi_"error")/15]_+ $
$ u_"bank" = [1 - abs(phi)/10]_+ quad u_"speed" = [1 - abs(V-28)/12]_+ $
Here $x,z$ are touchdown positions (m); $v_"sink"$ is vertical speed (m/s);
$psi_"error"$ and $phi$ are heading error and bank (degrees); $V$ is airspeed (m/s).
All values were frozen at first main-gear contact. Without touchdown, $Q=0$.

*Limitation:* approach tracking and pitch oscillations did not affect V1. A failed rollout could still receive up to 49 points; a safe successful rollout was floored at 50.

*V2 replaces these quality rules, not the existing touchdown-safety and completed-rollout conditions.* Historical V1 records remain unchanged and are not ranked against V2.

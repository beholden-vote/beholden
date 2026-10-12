// Generates and checks the WO-38 colour ramp. Run: node src/ui/stand/ramp.check.mjs
// Prints the stops to paste into lib/positions.ts (RAMP) and the colour-vision report.
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const enc = (c) => { c = Math.min(1, Math.max(0, c)); return c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055; };
const mul = (M, v) => M.map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);
const A = [[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566], [0.0883024619, 0.2817188376, 0.6299787005]];
const B = [[0.2104542553, 0.793617785, -0.0040720468], [1.9779984951, -2.428592205, 0.4505937099], [0.0259040371, 0.7827717662, -0.808675766]];
const Ai = [[4.0767416621, -3.3077115913, 0.2309699292], [-1.2684380046, 2.6097574011, -0.3413193965], [-0.0041960863, -0.7034186147, 1.707614701]];
const Bi = [[1, 0.3963377774, 0.2158037573], [1, -0.1055613458, -0.0638541728], [1, -0.0894841775, -1.291485548]];
const fromLab = (lab) => mul(Ai, mul(Bi, lab).map((x) => x ** 3));            // linear rgb
const toLab = (lin3) => mul(B, mul(A, lin3).map(Math.cbrt));
const lch = (L, C, h) => [L, C * Math.cos((h * Math.PI) / 180), C * Math.sin((h * Math.PI) / 180)];
const inGamut = (l) => l.every((x) => x > -1e-4 && x < 1 + 1e-4);
const Y = (l) => 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
const hex = (l) => "#" + l.map((x) => Math.round(enc(x) * 255).toString(16).padStart(2, "0")).join("");
const dE = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

const L = 0.66, H_LOW = 305, H_HIGH = 100;   // violet <- neutral -> olive-yellow, one lightness
const maxC = (h) => { let c = 0; for (let C = 0.01; C < 0.3; C += 0.002) { if (!inGamut(fromLab(lch(L, C, h)))) break; c = C; } return c; };
const C = Math.min(maxC(H_LOW), maxC(H_HIGH)) * 0.92;   // the SAME chroma at both ends
const N = 9;
const stops = [];
for (let i = 0; i < N; i++) {
  const t = (i - (N - 1) / 2) / ((N - 1) / 2);          // -1 .. 1
  stops.push(fromLab(lch(L, Math.abs(t) * C, t < 0 ? H_LOW : H_HIGH)));
}
console.log("stops", stops.map(hex).join(" "), " chroma", C.toFixed(3), "OKLab L", L);
console.log("relative luminance min/max", Math.min(...stops.map(Y)).toFixed(4), Math.max(...stops.map(Y)).toFixed(4));

// Machado et al. 2009, severity 1.0 (applied to linear rgb)
const SIM = {
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
  tritanopia: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
const bg = toLab([lin(4 / 255), lin(18 / 255), lin(28 / 255)]);
for (const [name, M] of [["normal", null], ...Object.entries(SIM)]) {
  const seen = stops.map((s) => (M ? mul(M, s).map((x) => Math.min(1, Math.max(0, x))) : s));
  const labs = seen.map(toLab);
  const ends = dE(labs[0], labs[N - 1]);
  const step = Math.min(...labs.slice(1).map((l, i) => dE(l, labs[i])));
  console.log(name.padEnd(13), "ends dE", ends.toFixed(3), " min adjacent-step dE", step.toFixed(3),
    " ends dL", Math.abs(labs[0][0] - labs[N - 1][0]).toFixed(3));
}
// distance of the ramp ends to each party hue (so a numeric fill is not read as a party)
const party = { D: "#4b83bd", R: "#c25b5b", I: "#8f8f5e", L: "#9a8a5a", G: "#5b9a63", NP: "#64717c" };
const px = (h) => toLab([1, 3, 5].map((i) => lin(parseInt(h.slice(i, i + 2), 16) / 255)));
for (const [k, h] of Object.entries(party)) {
  console.log("dE ramp ends vs party", k, dE(toLab(stops[0]), px(h)).toFixed(3), dE(toLab(stops[N - 1]), px(h)).toFixed(3));
}
void bg;

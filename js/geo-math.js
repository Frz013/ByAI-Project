/**
 * geo-math.js
 * Utilitas parsing dan transformasi geometri + formatter simbolik
 * Mengandalkan math.js (global `math`) untuk evaluasi fungsi aman.
 */

// ===== Helpers =====
const GeoMath = (() => {
  const EPS = 1e-9;

  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function round(n, d = 2) {
    if (!isFinite(n)) return n;
    const f = Math.pow(10, d);
    return Math.round(n * f) / f;
  }

  function isNumberLike(v) {
    return typeof v === "number" && !Number.isNaN(v) && Number.isFinite(v);
  }

  function normalizeLine(A, B, C) {
    // Normalisasi agar sqrt(A^2+B^2)=1 untuk stabilitas (kecuali A=B=0)
    const norm = Math.hypot(A, B);
    if (norm < EPS) return { A, B, C };
    const s = 1 / norm;
    return { A: A * s, B: B * s, C: C * s };
  }

  // ===== Parsers =====

  /**
   * Parse daftar titik dari string menjadi array [ [x,y], ... ]
   * Format didukung:
   * - (x,y); (x2,y2)
   * - baris: (x,y)
   * - x,y (tanpa kurung)
   * - angka dipisah koma/space
   */
  function parsePoints(text, limit = 200) {
    if (!text || !text.trim()) return [];
    const raw = text
      .replace(/\r/g, "")
      .split(/[;\n]/)
      .map(s => s.trim())
      .filter(Boolean);

    const points = [];
    for (let s of raw) {
      // ambil dua angka (boleh dalam kurung)
      const m = s.match(/-?\d*\.?\d+(?:e-?\d+)?/gi);
      if (!m || m.length < 2) continue;
      const x = parseFloat(m[0]);
      const y = parseFloat(m[1]);
      if (isNumberLike(x) && isNumberLike(y)) {
        points.push([x, y]);
        if (points.length >= limit) break;
      }
    }
    return points;
  }

  /**
   * Parse garis dari format slope y = m x + b ke Ax + By + C = 0
   * y - mx - b = 0 => (-m) x + 1*y + (-b) = 0 atau m x - y + b = 0
   * Kita gunakan: A = m, B = -1, C = b untuk konsistensi (y = mx + b -> m x - y + b = 0)
   */
  function parseLineSlope(mStr, bStr) {
    const m = parseFloat(String(mStr).trim());
    const b = parseFloat(String(bStr).trim());
    if (!isNumberLike(m) || !isNumberLike(b)) {
      return null;
    }
    const { A, B, C } = normalizeLine(m, -1, b);
    return { A, B, C };
  }

  /**
   * Parse garis dari format umum Ax + By + C = 0 (langsung)
   */
  function parseLineStandard(aStr, bStr, cStr) {
    const A = parseFloat(String(aStr).trim());
    const B = parseFloat(String(bStr).trim());
    const C = parseFloat(String(cStr).trim());
    if (!isNumberLike(A) || !isNumberLike(B) || !isNumberLike(C)) {
      return null;
    }
    return normalizeLine(A, B, C);
  }

  /**
   * Compile fungsi f(x) dari string menggunakan math.js
   * Mengembalikan { eval(x), original: expr }
   */
  function compileFunction(expr) {
    if (!expr || !expr.trim()) return null;
    let node;
    try {
      node = math.parse(expr);
    } catch (e) {
      return null;
    }
    // Pastikan hanya variabel x yang digunakan
    const vars = node.filter(n => n.isSymbolNode).map(n => n.name);
    const uniq = Array.from(new Set(vars));
    for (const v of uniq) {
      if (v !== "x" && v !== "e" && v !== "pi") {
        // variabel lain tidak diizinkan
        return null;
      }
    }
    let code;
    try {
      code = node.compile();
    } catch (e) {
      return null;
    }
    function evalAt(x) {
      try {
        const res = code.evaluate({ x, e: Math.E, pi: Math.PI });
        if (!isNumberLike(res)) return NaN;
        return res;
      } catch {
        return NaN;
      }
    }
    return { eval: evalAt, original: expr };
  }

  // ===== Transforms =====

  function translatePoint([x, y], dx, dy) {
    return [x + dx, y + dy];
  }

  function rotatePoint([x, y], deg, cx = 0, cy = 0) {
    const th = (deg * Math.PI) / 180;
    const cos = Math.cos(th);
    const sin = Math.sin(th);
    const tx = x - cx;
    const ty = y - cy;
    const xr = cx + cos * tx - sin * ty;
    const yr = cy + sin * tx + cos * ty;
    return [xr, yr];
  }

  function dilatePoint([x, y], k, cx = 0, cy = 0) {
    const tx = x - cx;
    const ty = y - cy;
    return [cx + k * tx, cy + k * ty];
  }

  // Refleksi titik terhadap garis Ax + By + C = 0
  function reflectPointAcrossLine([x, y], A, B, C) {
    const denom = A * A + B * B;
    if (denom < EPS) return [x, y];
    const d = (A * x + B * y + C) / denom;
    const xr = x - 2 * A * d;
    const yr = y - 2 * B * d;
    return [xr, yr];
  }

  // Ambil dua titik pada garis Ax + By + C = 0
  function twoPointsOnLine(A, B, C) {
    if (Math.abs(B) > EPS) {
      const x0 = 0;
      const y0 = -C / B;
      const x1 = 1;
      const y1 = -(A * 1 + C) / B;
      return [[x0, y0], [x1, y1]];
    } else if (Math.abs(A) > EPS) {
      const xconst = -C / A;
      return [[xconst, 0], [xconst, 1]];
    } else {
      // Degenerate, default points
      return [[0, 0], [1, 0]];
    }
  }

  // Bentuk garis dari dua titik
  function lineFromTwoPoints([x1, y1], [x2, y2]) {
    const A = y1 - y2;
    const B = x2 - x1;
    const C = x1 * y2 - x2 * y1;
    return normalizeLine(A, B, C);
  }

  /**
   * Transform garis:
   * - Translasi: C' = C - A*dx - B*dy
   * - Lainnya: transform 2 titik lalu re-fit
   */
  function transformLine({ A, B, C }, kind, params) {
    if (kind === "translate") {
      const dx = params.dx || 0;
      const dy = params.dy || 0;
      // Ax + By + C = 0 -> translasi (x',y')=(x+dx,y+dy) -> C' = C - A*dx - B*dy
      const C2 = C - A * dx - B * dy;
      return normalizeLine(A, B, C2);
    }
    // Ambil 2 titik, transform keduanya
    const [p1, p2] = twoPointsOnLine(A, B, C);
    let t1, t2;
    if (kind === "rotate") {
      const { deg = 0, cx = 0, cy = 0 } = params || {};
      t1 = rotatePoint(p1, deg, cx, cy);
      t2 = rotatePoint(p2, deg, cx, cy);
    } else if (kind === "reflect") {
      const { rA, rB, rC } = params || {};
      t1 = reflectPointAcrossLine(p1, rA, rB, rC);
      t2 = reflectPointAcrossLine(p2, rA, rB, rC);
    } else if (kind === "dilate") {
      const { k = 1, cx = 0, cy = 0 } = params || {};
      t1 = dilatePoint(p1, k, cx, cy);
      t2 = dilatePoint(p2, k, cx, cy);
    } else {
      return normalizeLine(A, B, C);
    }
    return lineFromTwoPoints(t1, t2);
  }

  /**
   * Sampling fungsi pada domain [minX, maxX] menjadi list titik
   * - step adaptif: target 600 titik, clamp 1500
   */
  function functionSample(fn, minX, maxX) {
    const length = Math.max(1e-6, Math.abs(maxX - minX));
    let target = 600;
    const step = length / target;
    const points = [];
    let i = 0;
    for (let x = minX; x <= maxX + 1e-12; x += step) {
      if (i++ > 1500) break;
      const y = fn.eval(x);
      if (isNumberLike(y) && isFinite(y)) {
        // Skip nilai terlalu besar agar tidak meledak
        if (Math.abs(y) < 1e6) {
          points.push([x, y]);
        }
      }
    }
    return points;
  }

  // ===== Formatters =====

  function prettyLine(A, B, C) {
    // Bentuk umum
    const Au = round(A, 2);
    const Bu = round(B, 2);
    const Cu = round(C, 2);

    // Bentuk slope
    let slopeForm = "—";
    if (Math.abs(B) > EPS) {
      const m = -A / B;
      const b = -C / B;
      slopeForm = `y = ${round(m, 2)}x ${b >= 0 ? "+ " + round(b, 2) : "- " + round(-b, 2)}`;
    } else if (Math.abs(A) > EPS) {
      const xconst = -C / A;
      slopeForm = `x = ${round(xconst, 2)}`;
    }

    // Umum
    const sA = Au.toString();
    const sB = (Bu >= 0 ? "+ " : "- ") + Math.abs(Bu);
    const sC = (Cu >= 0 ? "+ " : "- ") + Math.abs(Cu);
    const general = `${sA}x ${sB}y ${sC} = 0`;

    return { general, slope: slopeForm };
  }

  function prettyFunctionTranslation(expr, dx, dy) {
    const dxStr = dx === 0 ? "x" : `x ${dx >= 0 ? "- " + round(dx, 2) : "+ " + round(-dx, 2)}`;
    const dyStr = dy === 0 ? "" : ` ${dy >= 0 ? "+ " + round(dy, 2) : "- " + round(-dy, 2)}`;
    return `y = (${expr.replace(/\s+/g, " ") .trim()}).dengan x→(${dxStr})${dyStr}`.replace(".dengan", " menjadi f(x - dx) + dy:\n y = " + expr.replace(/\s+/g, " ").trim() + " dengan substitusi x→(" + dxStr + ")" + dyStr);
  }

  function parametricForTransform(expr, kind, params) {
    // Bentuk informatif parametrik x'(t), y'(t)
    if (kind === "translate") {
      const { dx = 0, dy = 0 } = params || {};
      return `x'(t) = t + ${round(dx, 2)},  y'(t) = f(t) + ${round(dy, 2)}`;
    }
    if (kind === "rotate") {
      const { deg = 0, cx = 0, cy = 0 } = params || {};
      const th = (deg * Math.PI) / 180;
      const cos = round(Math.cos(th), 4);
      const sin = round(Math.sin(th), 4);
      return `x'(t) = ${round(cx, 2)} + ${cos}(t - ${round(cx, 2)}) - ${sin}(f(t) - ${round(cy, 2)})\n` +
             `y'(t) = ${round(cy, 2)} + ${sin}(t - ${round(cx, 2)}) + ${cos}(f(t) - ${round(cy, 2)})`;
    }
    if (kind === "dilate") {
      const { k = 1, cx = 0, cy = 0 } = params || {};
      return `x'(t) = ${round(cx, 2)} + ${round(k, 2)}(t - ${round(cx, 2)}),  y'(t) = ${round(cy, 2)} + ${round(k, 2)}(f(t) - ${round(cy, 2)})`;
    }
    if (kind === "reflect") {
      // Untuk umum, tampilkan koefisien garis pantul
      const { rA = 0, rB = 1, rC = 0, m = null, b = null } = params || {};
      let lineDesc = `Ax + By + C = 0 dengan A=${round(rA,2)}, B=${round(rB,2)}, C=${round(rC,2)}`;
      if (m !== null && b !== null) {
        lineDesc = `y = ${round(m, 2)}x ${b >= 0 ? "+ " + round(b, 2) : "- " + round(-b, 2)}`;
      }
      return `Refleksi terhadap ${lineDesc}. Bentuk eksplisit f' sulit; ditampilkan sebagai sampel titik.`;
    }
    return "—";
  }

  return {
    EPS,
    clamp,
    round,

    // parse
    parsePoints,
    parseLineSlope,
    parseLineStandard,
    compileFunction,

    // transforms
    translatePoint,
    rotatePoint,
    dilatePoint,
    reflectPointAcrossLine,
    transformLine,

    // helpers
    twoPointsOnLine,
    lineFromTwoPoints,
    functionSample,

    // formatters
    prettyLine,
    prettyFunctionTranslation,
    parametricForTransform,
  };
})();

window.GeoMath = GeoMath;

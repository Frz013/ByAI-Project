/**
 * geo-transform.js
 * Implementasi kalkulator transformasi geometri TANPA Desmos.
 * Fokus pada input dan hasil bayangan (output numerik + hasil simbolik).
 * Menggunakan GeoMath (js/geo-math.js) dan math.js
 */

(function () {
  function onReady(cb) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", cb);
    } else {
      cb();
    }
  }

  onReady(init);

  // Undo snapshot (1 langkah)
  let undoSnapshot = null;

  // ===== Helpers DOM =====
  function byId(id) {
    return document.getElementById(id);
  }

  function toggle(id, show) {
    const el = byId(id);
    if (!el) return;
    el.classList.toggle("hidden", !show);
  }

  function getRadioValue(name) {
    const el = document.querySelector(`input[name="${name}"]:checked`);
    return el ? el.value : null;
  }

  function setRadioValue(name, value) {
    const el = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (el) el.checked = true;
  }

  function setPre(id, text) {
    const el = byId(id);
    if (el) el.textContent = text;
  }

  function setBoxVisibility() {
    const showOrig = byId("showOriginal").checked;
    const showTrans = byId("showTransformed").checked;
    toggle("origBox", showOrig);
    toggle("transBox", showTrans);
  }

  function round(n, d = 2) {
    return GeoMath.round(n, d);
  }

  function fmtPoint(p) {
    return `(${round(p[0], 2)}, ${round(p[1], 2)})`;
  }

  function fmtPointList(points, limit = 200) {
    if (!points || !points.length) return "—";
    const lim = Math.max(0, Math.min(limit, points.length));
    const shown = points.slice(0, lim).map(fmtPoint).join("\n");
    if (lim < points.length) {
      return shown + `\n... (${points.length - lim} titik lagi)`;
    }
    return shown;
  }

  // ===== Init & UI Binding =====
  function init() {
    bindUI();
    updateVisibility(); // tampilkan form sesuai pilihan awal
    setBoxVisibility();
    render(); // render awal
  }

  function bindUI() {
    // Obj type select
    const objTypeEl = byId("objType");
    if (objTypeEl) {
      objTypeEl.addEventListener("change", () => {
        updateVisibility();
        render();
      });
    }

    // Line format radios
    document.querySelectorAll('input[name="lineFormat"]').forEach((el) => {
      el.addEventListener("change", () => {
        updateVisibility();
        render();
      });
    });

    // Transform type chip buttons
    const transBtns = document.querySelectorAll('#transTypeBtns .chip');
    transBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        setTransType(btn.dataset.value);
        updateVisibility();
        render();
      });
    });

    // Reflect type chip buttons
    const reflBtns = document.querySelectorAll('#reflectTypeBtns .chip');
    reflBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        setReflectType(btn.dataset.value);
        updateVisibility();
        render();
      });
    });

    // Function mode chip buttons
    const funcModeBtns = document.querySelectorAll('#funcModeBtns .chip');
    funcModeBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        setFuncMode(btn.dataset.value);
        updateVisibility();
        render();
      });
    });

    // Poly degree select
    const polyDeg = byId("polyDegree");
    if (polyDeg) {
      polyDeg.addEventListener("change", () => {
        updateVisibility();
        render();
      });
    }

    // Number inputs only (sliders removed)
    addInput("dxNum");
    addInput("dyNum");

    addInput("thetaNum");
    addInput("cx");
    addInput("cy");

    addInput("kNum");
    addInput("dcx");
    addInput("dcy");

    addInput("lineM");
    addInput("lineB");
    addInput("lineA");
    addInput("lineBstd");
    addInput("lineC");
    addInput("refM");
    addInput("refB");

    addInput("pointsInput", "textarea");
    addInput("funcExpr");
    addInput("polyA3");
    addInput("polyA2");
    addInput("polyA1");
    addInput("polyA0");
    addInput("minX");
    addInput("maxX");

    // Toggles
    const showOrigEl = byId("showOriginal");
    const showTransEl = byId("showTransformed");
    if (showOrigEl) showOrigEl.addEventListener("change", () => { setBoxVisibility(); render(); });
    if (showTransEl) showTransEl.addEventListener("change", () => { setBoxVisibility(); render(); });

    // Buttons
    const applyBtn = byId("applyBtn");
    if (applyBtn) {
      applyBtn.addEventListener("click", () => {
        undoSnapshot = takeSnapshot();
        render();
      });
    }

    const undoBtn = byId("undoBtn");
    if (undoBtn) {
      undoBtn.addEventListener("click", () => {
        if (!undoSnapshot) return;
        restoreSnapshot(undoSnapshot);
        undoSnapshot = null;
        render();
      });
    }

    const resetBtn = byId("resetBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        resetForm();
        render();
      });
    }
  }

  function addInput(id) {
    const el = byId(id);
    if (!el) return;
    el.addEventListener("input", () => render());
  }

  function linkRangeAndNumber(rangeId, numId) {
    const r = byId(rangeId);
    const n = byId(numId);
    if (!r || !n) return;
    const handler = () => {
      if (document.activeElement === r) n.value = r.value;
      else if (document.activeElement === n) r.value = n.value;
      render();
    };
    r.addEventListener("input", handler);
    n.addEventListener("input", handler);
  }

  // Helpers for chip groups (Transformasi & Refleksi)
  function getTransType() {
    const active = document.querySelector('#transTypeBtns .chip.active');
    return active ? active.dataset.value : "translate";
  }
  function setTransType(val) {
    const group = document.getElementById("transTypeBtns");
    if (!group) return;
    group.querySelectorAll(".chip").forEach((b) => {
      const isActive = b.dataset.value === String(val);
      b.classList.toggle("active", isActive);
      b.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }
  function getReflectType() {
    const active = document.querySelector('#reflectTypeBtns .chip.active');
    return active ? active.dataset.value : "x";
  }
  function setReflectType(val) {
    const group = document.getElementById("reflectTypeBtns");
    if (!group) return;
    group.querySelectorAll(".chip").forEach((b) => {
      const isActive = b.dataset.value === String(val);
      b.classList.toggle("active", isActive);
      b.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  // Function mode helpers
  function getFuncMode() {
    const active = document.querySelector('#funcModeBtns .chip.active');
    return active ? active.dataset.value : "free";
  }
  function setFuncMode(val) {
    const group = document.getElementById("funcModeBtns");
    if (!group) return;
    group.querySelectorAll(".chip").forEach((b) => {
      const isActive = b.dataset.value === String(val);
      b.classList.toggle("active", isActive);
      b.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  // Make function input friendlier (basic normalization)
  function normalizeExpr(expr) {
    if (!expr) return expr;
    let s = String(expr)
      .replace(/π/gi, "pi")
      .replace(/\u03C0/gi, "pi"); // pi char fallback

    // common aliases
    s = s.replace(/\bln\b/gi, "log");

    // insert * between number and ( or x
    s = s.replace(/(\d)\s*(x|\()/gi, "$1*$2");
    // insert * between ) and x or (
    s = s.replace(/\)\s*(x|\()/g, ")*$1");
    // insert * between x and (
    s = s.replace(/x\s*\(/gi, "x*(");

    // wrap trig/log when written as "sin x", "cos x", etc.
    const funs = ["sin", "cos", "tan", "exp", "log"];
    for (const f of funs) {
      const re = new RegExp(`\\b${f}\\s*x\\b`, "gi");
      s = s.replace(re, `${f}(x)`);
    }

    // clean multiple spaces
    s = s.replace(/\s+/g, " ").trim();
    return s;
  }

  // ===== Form Visibility =====
  function updateVisibility() {
    const objType = byId("objType").value;
    toggle("pointInputs", objType === "point");
    toggle("lineInputs", objType === "line");
    toggle("funcInputs", objType === "function");

    const lineFmt = getRadioValue("lineFormat");
    toggle("lineSlopeBox", lineFmt === "slope");
    toggle("lineStdBox", lineFmt === "standard");

    const transType = getTransType();
    toggle("boxTranslate", transType === "translate");
    toggle("boxRotate", transType === "rotate");
    toggle("boxReflect", transType === "reflect");
    toggle("boxDilate", transType === "dilate");

    const refType = getReflectType();
    toggle("reflectGeneralBox", refType === "general");

    // Function mode visibility
    const fmode = getFuncMode();
    toggle("funcFreeBox", fmode === "free");
    toggle("funcPolyBox", fmode === "poly");

    // Poly degree coefficient boxes
    const deg = parseInt((byId("polyDegree") && byId("polyDegree").value) || "2", 10);
    toggle("coefA3Box", deg === 3);
    toggle("coefA2Box", deg >= 2);
    toggle("coefA1Box", deg >= 1);
    // a0 always shown (inside row)
  }

  // ===== Snapshot for Undo/Reset =====
  function takeSnapshot() {
    const fields = [
      "objType",
      "pointsInput",
      "lineM",
      "lineB",
      "lineA",
      "lineBstd",
      "lineC",
      "funcExpr",
      "polyDegree",
      "polyA3",
      "polyA2",
      "polyA1",
      "polyA0",
      "minX",
      "maxX",
      "dxNum",
      "dyNum",
      "thetaNum",
      "cx",
      "cy",
      "kNum",
      "dcx",
      "dcy",
      "refM",
      "refB",
      "showOriginal",
      "showTransformed",
    ];

    const radios = {
      lineFormat: getRadioValue("lineFormat"),
      transType: getTransType(),
      reflectType: getReflectType(),
      funcMode: getFuncMode(),
    };

    const data = { values: {}, radios };
    fields.forEach((id) => {
      const el = byId(id);
      if (!el) return;
      if (el.type === "checkbox") data.values[id] = el.checked;
      else data.values[id] = el.value;
    });
    return data;
  }

  function restoreSnapshot(snap) {
    Object.entries(snap.values).forEach(([id, val]) => {
      const el = byId(id);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!val;
      else el.value = val;
    });
    setRadioValue("lineFormat", snap.radios.lineFormat);
    setTransType(snap.radios.transType);
    setReflectType(snap.radios.reflectType);
    setFuncMode(snap.radios.funcMode || "free");
    updateVisibility();
    setBoxVisibility();
  }

  function resetForm() {
    // Defaults
    byId("objType").value = "point";
    byId("pointsInput").value = "(1,2); (3,-1); (0,0)";

    setRadioValue("lineFormat", "slope");
    byId("lineM").value = "1";
    byId("lineB").value = "0";
    byId("lineA").value = "";
    byId("lineBstd").value = "";
    byId("lineC").value = "";

    // Function defaults
    setFuncMode("free");
    byId("funcExpr").value = "x^2";
    const pd = byId("polyDegree");
    if (pd) pd.value = "2";
    if (byId("polyA3")) byId("polyA3").value = "0";
    if (byId("polyA2")) byId("polyA2").value = "1";
    if (byId("polyA1")) byId("polyA1").value = "0";
    if (byId("polyA0")) byId("polyA0").value = "0";
    byId("minX").value = "-10";
    byId("maxX").value = "10";

    setTransType("translate");
    byId("dxNum").value = "0";
    byId("dyNum").value = "0";

    byId("thetaNum").value = "0";
    byId("cx").value = "0";
    byId("cy").value = "0";

    byId("kNum").value = "1";
    byId("dcx").value = "0";
    byId("dcy").value = "0";

    setReflectType("x");
    byId("refM").value = "1";
    byId("refB").value = "0";

    byId("showOriginal").checked = true;
    byId("showTransformed").checked = true;

    updateVisibility();
    setBoxVisibility();
  }

  // ===== Data Extraction =====
  function getObjectData() {
    const objType = byId("objType").value;
    if (objType === "point") {
      const txt = byId("pointsInput").value;
      const pts = GeoMath.parsePoints(txt, 200);
      return { type: "point", points: pts };
    }
    if (objType === "line") {
      const fmt = getRadioValue("lineFormat");
      if (fmt === "slope") {
        const m = byId("lineM").value;
        const b = byId("lineB").value;
        const L = GeoMath.parseLineSlope(m, b);
        if (!L) return { type: "line", error: "Masukkan m dan b yang valid." };
        return { type: "line", line: L };
      } else {
        const A = byId("lineA").value;
        const B = byId("lineBstd").value;
        const C = byId("lineC").value;
        const L = GeoMath.parseLineStandard(A, B, C);
        if (!L) return { type: "line", error: "Masukkan A, B, C yang valid." };
        return { type: "line", line: L };
      }
    }
    if (objType === "function") {
      const mode = getFuncMode();
      let expr = "";
      if (mode === "poly") {
        const deg = parseInt((byId("polyDegree") && byId("polyDegree").value) || "2", 10);
        const a3 = parseFloat(byId("polyA3") ? byId("polyA3").value : "0") || 0;
        const a2 = parseFloat(byId("polyA2") ? byId("polyA2").value : "0") || 0;
        const a1 = parseFloat(byId("polyA1") ? byId("polyA1").value : "0") || 0;
        const a0 = parseFloat(byId("polyA0") ? byId("polyA0").value : "0") || 0;
        const parts = [];
        if (deg === 3) {
          if (a3 !== 0) parts.push(`${a3}*x^3`);
          if (a2 !== 0) parts.push(`${a2}*x^2`);
          if (a1 !== 0) parts.push(`${a1}*x`);
          if (a0 !== 0) parts.push(`${a0}`);
        } else if (deg === 2) {
          if (a2 !== 0) parts.push(`${a2}*x^2`);
          if (a1 !== 0) parts.push(`${a1}*x`);
          if (a0 !== 0) parts.push(`${a0}`);
        } else if (deg === 1) {
          if (a1 !== 0) parts.push(`${a1}*x`);
          if (a0 !== 0) parts.push(`${a0}`);
        } else {
          parts.push(`${a0}`);
        }
        expr = parts.join(" + ").replace(/\+\s*-/, "- ").replace(/\s+\+\s+$/, "");
        if (!expr) expr = "0";
      } else {
        expr = normalizeExpr(byId("funcExpr").value);
      }

      const fn = GeoMath.compileFunction(expr);
      const minX = parseFloat(byId("minX").value);
      const maxX = parseFloat(byId("maxX").value);
      if (!fn) return { type: "function", error: "Ekspresi fungsi tidak valid." };
      if (!Number.isFinite(minX) || !Number.isFinite(maxX) || minX >= maxX) {
        return { type: "function", error: "Domain X tidak valid." };
      }
      return { type: "function", fn, expr, minX, maxX };
    }
    return { type: "unknown", error: "Jenis objek tidak dikenal." };
  }

  function getTransformParams() {
    const kind = getTransType();
    if (kind === "translate") {
      return {
        kind,
        dx: parseFloat(byId("dxNum").value) || 0,
        dy: parseFloat(byId("dyNum").value) || 0,
      };
    }
    if (kind === "rotate") {
      return {
        kind,
        deg: parseFloat(byId("thetaNum").value) || 0,
        cx: parseFloat(byId("cx").value) || 0,
        cy: parseFloat(byId("cy").value) || 0,
      };
    }
    if (kind === "reflect") {
      const rt = getReflectType();
      if (rt === "x") {
        // y=0 -> line: 0*x + 1*y + 0 = 0 => A=0, B=1, C=0
        return { kind, rA: 0, rB: 1, rC: 0, rt };
      } else if (rt === "y") {
        // x=0 -> 1*x + 0*y + 0 = 0
        return { kind, rA: 1, rB: 0, rC: 0, rt };
      } else if (rt === "yx") {
        // y - x = 0 -> A=-1, B=1, C=0
        return { kind, rA: -1, rB: 1, rC: 0, rt };
      } else if (rt === "ynx") {
        // y + x = 0 -> A=1, B=1, C=0
        return { kind, rA: 1, rB: 1, rC: 0, rt };
      } else {
        const m = parseFloat(byId("refM").value) || 0;
        const b = parseFloat(byId("refB").value) || 0;
        // gunakan normalisasi konsisten: y = m x + b -> m x - y + b = 0
        const norm = GeoMath.parseLineSlope(m, b);
        return { kind, rA: norm.A, rB: norm.B, rC: norm.C, rt, m, b };
      }
    }
    if (kind === "dilate") {
      return {
        kind,
        k: parseFloat(byId("kNum").value) || 1,
        cx: parseFloat(byId("dcx").value) || 0,
        cy: parseFloat(byId("dcy").value) || 0,
      };
    }
    return { kind: "none" };
  }

  // ===== Transform utilities =====
  function applyPointTransform(pt, trans) {
    const [x, y] = pt;
    if (trans.kind === "translate") {
      return GeoMath.translatePoint([x, y], trans.dx || 0, trans.dy || 0);
    }
    if (trans.kind === "rotate") {
      return GeoMath.rotatePoint([x, y], trans.deg || 0, trans.cx || 0, trans.cy || 0);
    }
    if (trans.kind === "reflect") {
      const { rA = 0, rB = 1, rC = 0 } = trans;
      return GeoMath.reflectPointAcrossLine([x, y], rA, rB, rC);
    }
    if (trans.kind === "dilate") {
      return GeoMath.dilatePoint([x, y], trans.k || 1, trans.cx || 0, trans.cy || 0);
    }
    return [x, y];
  }

  // ===== Rendering =====
  function render() {
    const obj = getObjectData();
    const trans = getTransformParams();

    // Set visibilitas box hasil sesuai checkbox
    setBoxVisibility();

    // Reset output
    setPre("symbolicOut", "—");
    setPre("origOut", "—");
    setPre("transOut", "—");

    // Validasi umum
    if (obj.error) {
      setPre("symbolicOut", `Error: ${obj.error}`);
      setPre("origOut", "—");
      setPre("transOut", "—");
      return;
    }

    const showOriginal = byId("showOriginal").checked;
    const showTransformed = byId("showTransformed").checked;

    if (obj.type === "point") {
      // Points: tampilkan daftar
      const pts = obj.points || [];
      if (showOriginal) {
        setPre("origOut", fmtPointList(pts, 400));
      }
      if (showTransformed) {
        const tpts = pts.map((p) => applyPointTransform(p, trans));
        setPre("transOut", fmtPointList(tpts, 400));
      }
      // Hasil simbolik sederhana
      setPre("symbolicOut", describeTransformForPoints(trans));
      return;
    }

    if (obj.type === "line") {
      // Line: gunakan formatter simbolik dan transformasi garis
      const L = obj.line;
      const baseFmt = GeoMath.prettyLine(L.A, L.B, L.C);
      if (showOriginal) {
        setPre("origOut", `Bentuk umum:\n${baseFmt.general}\n\nBentuk slope:\n${baseFmt.slope}`);
      }
      if (showTransformed) {
        const LT = GeoMath.transformLine(L, trans.kind, trans);
        const tfmt = GeoMath.prettyLine(LT.A, LT.B, LT.C);
        setPre("transOut", `Bentuk umum:\n${tfmt.general}\n\nBentuk slope:\n${tfmt.slope}`);
      }
      setPre("symbolicOut", describeTransformForLine(trans));
      return;
    }

    if (obj.type === "function") {
      // Function: sampling ke titik, lalu transform tiap titik
      const { fn, expr, minX, maxX } = obj;
      // Hasil simbolik:
      if (trans.kind === "translate") {
        setPre("symbolicOut", GeoMath.prettyFunctionTranslation(expr, trans.dx || 0, trans.dy || 0));
      } else {
        setPre("symbolicOut", GeoMath.parametricForTransform(expr, trans.kind, trans));
      }

      // Sampling
      const samples = GeoMath.functionSample(fn, minX, maxX); // [[x,y],...]
      if (showOriginal) {
        setPre("origOut", fmtPointList(samples, 600));
      }
      if (showTransformed) {
        const ts = samples.map((p) => applyPointTransform(p, trans));
        setPre("transOut", fmtPointList(ts, 600));
      }
      return;
    }

    // Unknown
    setPre("symbolicOut", "—");
    setPre("origOut", "—");
    setPre("transOut", "—");
  }

  // ===== Descriptions =====
  function describeTransformForPoints(trans) {
    if (trans.kind === "translate") {
      return `Translasi titik: (x, y) -> (x + ${round(trans.dx || 0)}, y + ${round(trans.dy || 0)})`;
    }
    if (trans.kind === "rotate") {
      const deg = round(trans.deg || 0);
      const cx = round(trans.cx || 0);
      const cy = round(trans.cy || 0);
      return `Rotasi titik sebesar ${deg}° terhadap pusat (${cx}, ${cy}).`;
    }
    if (trans.kind === "reflect") {
      const { rA = 0, rB = 1, rC = 0, m = null, b = null } = trans;
      if (m !== null && b !== null) {
        return `Refleksi titik terhadap garis y = ${round(m, 2)}x ${b >= 0 ? "+ " + round(b, 2) : "- " + round(-b, 2)}.`;
      }
      return `Refleksi titik terhadap garis Ax + By + C = 0 dengan A=${round(rA,2)}, B=${round(rB,2)}, C=${round(rC,2)}.`;
    }
    if (trans.kind === "dilate") {
      const k = round(trans.k || 1);
      const cx = round(trans.cx || 0);
      const cy = round(trans.cy || 0);
      return `Dilatasi titik dengan faktor k=${k} berpusat di (${cx}, ${cy}).`;
    }
    return "Tidak ada transformasi.";
  }

  function describeTransformForLine(trans) {
    if (trans.kind === "translate") {
      return `Translasi garis: (dx, dy) = (${round(trans.dx || 0)}, ${round(trans.dy || 0)}).`;
    }
    if (trans.kind === "rotate") {
      return `Rotasi garis sebesar ${round(trans.deg || 0)}° terhadap pusat (${round(trans.cx || 0)}, ${round(trans.cy || 0)}).`;
    }
    if (trans.kind === "reflect") {
      const { rA = 0, rB = 1, rC = 0, m = null, b = null } = trans;
      if (m !== null && b !== null) {
        return `Refleksi garis terhadap garis pantul y = ${round(m, 2)}x ${b >= 0 ? "+ " + round(b, 2) : "- " + round(-b, 2)}.`;
      }
      return `Refleksi garis terhadap Ax + By + C = 0 dengan A=${round(rA,2)}, B=${round(rB,2)}, C=${round(rC,2)}.`;
    }
    if (trans.kind === "dilate") {
      return `Dilatasi garis dengan faktor k=${round(trans.k || 1)} berpusat di (${round(trans.cx || 0)}, ${round(trans.cy || 0)}).`;
    }
    return "Tidak ada transformasi.";
  }

})();

/**
 * The calculator's arithmetic. Pure: no DOM, no globals, no React.
 *
 * A developer will try to break this within four seconds of landing on the
 * page, so it is the one part of the site that gets real tests.
 *
 * @typedef {{display: string, acc: number|null, op: string|null,
 *            fresh: boolean, repeat: {op: string, operand: number}|null}} CalcState
 */

/** The readout is nine cells wide. A `.` shares a cell with the digit before it. */
export const CELLS = 9;

/** The resting state of the whole site is always the brand. */
export const BRAND = '80085';

export const initial = () => ({
  display: BRAND,
  acc: null,
  op: null,
  fresh: true,
  repeat: null
});

const width = (s) => s.replace(/\./g, '').length;
const value = (s) => {
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
};

function expo(n) {
  for (let p = 4; p >= 0; p--) {
    const s = n.toExponential(p).replace('e+', 'E').replace('e-', 'E-');
    if (width(s) <= CELLS) return s;
  }
  return 'Error';
}

/**
 * Render a number for a nine-cell display.
 *
 * Precision is reduced until the result fits rather than truncated, so
 * `0.1 + 0.2` shows `0.3` and `1/3` shows `0.33333333` — both correct for the
 * hardware being imitated, and neither leaking float representation noise.
 */
export function fmt(n) {
  if (!Number.isFinite(n)) return 'Error';
  if (n === 0) return '0';
  const abs = Math.abs(n);
  if (abs >= 1e9 || abs < 1e-8) return expo(n);
  for (let p = CELLS; p >= 1; p--) {
    const s = String(Number(n.toPrecision(p)));
    if (!s.includes('e') && width(s) <= CELLS) return s;
  }
  return expo(n);
}

function apply(a, op, b) {
  switch (op) {
    case '+':
      return a + b;
    case '-':
      return a - b;
    case '*':
      return a * b;
    case '/':
      return b === 0 ? NaN : a / b;
    default:
      return b;
  }
}

/**
 * Advance the calculator by one keypress.
 *
 * Keys: `0`-`9` `.` `+` `-` `*` `/` `=` `%` `C` `back` `brand`.
 * Returns a new state; never mutates.
 *
 * @param {CalcState} state
 * @param {string} key
 * @returns {CalcState}
 */
export function press(state, key) {
  if (key === 'C') return { ...initial(), display: '0' };
  if (key === 'brand') return initial();

  // Error is sticky. Only C (or the long-press reset) gets you out, which is
  // what every physical calculator does and what a developer expects.
  if (state.display === 'Error') return state;

  if (key >= '0' && key <= '9') {
    if (state.fresh) return { ...state, display: key, fresh: false };
    if (width(state.display) >= CELLS) return state;
    const display = state.display === '0' ? key : state.display + key;
    return { ...state, display };
  }

  if (key === '.') {
    if (state.fresh) return { ...state, display: '0.', fresh: false };
    if (state.display.includes('.')) return state;
    if (width(state.display) >= CELLS) return state;
    return { ...state, display: state.display + '.' };
  }

  if (key === 'back') {
    if (state.fresh) return state;
    const display = state.display.slice(0, -1);
    return { ...state, display: display === '' || display === '-' ? '0' : display };
  }

  if (key === '%') {
    return { ...state, display: fmt(value(state.display) / 100), fresh: true };
  }

  if (key === '+' || key === '-' || key === '*' || key === '/') {
    // Chaining: `2 + 3 +` resolves the pending operation and shows 5, so the
    // readout always reflects what the machine currently knows.
    if (state.op !== null && !state.fresh) {
      const result = apply(state.acc, state.op, value(state.display));
      return {
        display: fmt(result),
        acc: Number.isFinite(result) ? result : null,
        op: Number.isFinite(result) ? key : null,
        fresh: true,
        repeat: null
      };
    }
    return { ...state, acc: value(state.display), op: key, fresh: true };
  }

  if (key === '=') {
    let result;
    let repeat;
    if (state.op !== null) {
      const operand = value(state.display);
      result = apply(state.acc, state.op, operand);
      repeat = { op: state.op, operand };
    } else if (state.repeat) {
      // Pressing `=` again repeats the last operation, as hardware does.
      result = apply(value(state.display), state.repeat.op, state.repeat.operand);
      repeat = state.repeat;
    } else {
      return state;
    }
    return {
      display: fmt(result),
      acc: null,
      op: null,
      fresh: true,
      repeat: Number.isFinite(result) ? repeat : null
    };
  }

  return state;
}

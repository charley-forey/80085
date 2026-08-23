/**
 * Seven-segment glyphs, drawn from the geometry we already own.
 *
 * The polygons below are lifted verbatim from public/80085-icon-black.svg —
 * the hand-built seven-segment `8` that is the project's icon. Rendering the
 * readout from this instead of a webfont means:
 *
 *   - no font licensing question (this geometry is ours)
 *   - ghost segments are free: unlit segments are simply drawn in --ghost
 *   - CLS is structural, not aspirational: every cell is the same fixed viewBox
 *
 * Segments use the standard a-g naming, packed MSB-first into 7 bits:
 *
 *        aaaa
 *       f    b
 *       f    b
 *        gggg
 *       e    c
 *       e    c
 *        dddd   .dp
 */

// prettier-ignore
const POLY = [
  '24.5,0 55.5,0 60,4.5 55.5,9 24.5,9 20,4.5',          // a  top
  '51,4.5 55.5,0 60,4.5 60,33.5 55.5,38 51,33.5',       // b  top right
  '51,46.5 55.5,42 60,46.5 60,75.5 55.5,80 51,75.5',    // c  bottom right
  '24.5,71 55.5,71 60,75.5 55.5,80 24.5,80 20,75.5',    // d  bottom
  '20,46.5 24.5,42 29,46.5 29,75.5 24.5,80 20,75.5',    // e  bottom left
  '20,4.5 24.5,0 29,4.5 29,33.5 24.5,38 20,33.5',       // f  top left
  '24.5,35.5 55.5,35.5 60,40 55.5,44.5 24.5,44.5 20,40' // g  middle
];

const DP = '64,71 68,75 64,79 60,75';

/**
 * Every character the readout can display. A calculator that cannot spell
 * `Error` is not a calculator, so the letters are not optional.
 */
// prettier-ignore
export const SEG = {
  '0': 0b1111110, '1': 0b0110000, '2': 0b1101101, '3': 0b1111001,
  '4': 0b0110011, '5': 0b1011011, '6': 0b1011111, '7': 0b1110000,
  '8': 0b1111111, '9': 0b1111011,
  '-': 0b0000001, ' ': 0b0000000,
  'E': 0b1001111, 'r': 0b0000101, 'o': 0b0011101, 'n': 0b0010101,
  // S and 5 are the same seven segments. Both spellings exist so the flipped
  // readout can be written as the word it is, rather than as a number that
  // happens to look like one.
  'S': 0b1011011, 's': 0b1011011,
  'A': 0b1110111, 'C': 0b1001110, 'F': 0b1000111, 'H': 0b0110111,
  'I': 0b0110000, 'L': 0b0001110, 'P': 0b1100111, 'U': 0b0111110,
  'b': 0b0011111, 'c': 0b0001101, 'd': 0b0111101, 'h': 0b0010111,
  'i': 0b0010000, 't': 0b0001111, 'u': 0b0011100, 'y': 0b0110011
};

/** The cell box: the 40x80 glyph plus room for the decimal point. */
export const VIEWBOX = '18 -2 52 84';

/**
 * One readout cell as an SVG string.
 *
 * Unlit segments are still drawn — that is the whole point. A real LCD shows
 * you its dark segments, and reproducing that is what makes this read as a
 * calculator rather than a number in a funny font.
 */
export function cell(char, dp = false) {
  const mask = SEG[char] ?? SEG[' '];
  const seg = POLY.map(
    (points, i) =>
      `<polygon class="${mask & (1 << (6 - i)) ? 'on' : 'off'}" points="${points}"/>`
  ).join('');
  return (
    `<svg class="seg" viewBox="${VIEWBOX}" aria-hidden="true" focusable="false">` +
    seg +
    `<polygon class="${dp ? 'on' : 'off'}" points="${DP}"/>` +
    `</svg>`
  );
}

/**
 * A whole readout: `value` right-aligned into `cells` fixed positions.
 *
 * A `.` never consumes a cell of its own — it lights the decimal point of the
 * digit it follows, exactly like the hardware. This is what keeps the readout
 * from reflowing when you type `0.1`.
 */
export function readout(value, cells = 9) {
  const chars = [];
  for (const ch of String(value)) {
    if (ch === '.' && chars.length) chars[chars.length - 1].dp = true;
    else chars.push({ ch, dp: false });
  }
  const padded = [
    ...Array(Math.max(0, cells - chars.length)).fill({ ch: ' ', dp: false }),
    ...chars.slice(-cells)
  ];
  return padded.map((c) => cell(c.ch, c.dp)).join('');
}

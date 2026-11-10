import { describe, expect, it } from "vitest";
import { converge, DEFAULT_MUSIC_VOLUME, musicVolume, PAD_S, sceneTiming } from "./montage";

// Mêmes cas que `test_converge_meets_in_the_middle_within_the_natural_limits` (backend/tests/test_montage.py).
describe("converge", () => {
  it("voix plus longue : voix accélérée, clip ralenti, au milieu, marge comprise", () => {
    const { duration, tempo, stretch } = converge(4.4, 3.4);
    expect(duration).toBeCloseTo(3.9);
    expect(tempo).toBeCloseTo(4.4 / 3.9);
    expect(stretch).toBeCloseTo((3.9 + PAD_S) / 3.4);
  });
  it("voix plus courte : voix ralentie, clip accéléré", () => {
    const { duration, tempo } = converge(3.0, 3.3);
    expect(duration).toBeCloseTo(3.15);
    expect(tempo).toBeCloseTo(3.0 / 3.15);
  });
  it("plafonds : la voix décide, le clip reste dans ses limites", () => {
    expect(converge(9, 3.3)).toMatchObject({ tempo: 1.4, stretch: 1.25 });
    expect(converge(1.5, 3.3)).toMatchObject({ tempo: 0.85, stretch: 0.8 });
  });
});

describe("sceneTiming", () => {
  it("durée de la scène = durée convergée + marge ; le clip joue à l'inverse de son ralentissement", () => {
    const t = sceneTiming(4.4, 3.4, 3);
    expect(t.duration).toBeCloseTo(3.9 + PAD_S);
    expect(t.rate).toBeCloseTo(3.4 / (3.9 + PAD_S));
  });
  it("tant qu'une durée manque, la durée du script et des vitesses normales", () => {
    expect(sceneTiming(undefined, 3.3, 3)).toEqual({ duration: 3, tempo: 1, rate: 1 });
    expect(sceneTiming(4, undefined, 3)).toEqual({ duration: 3, tempo: 1, rate: 1 });
  });
});

// Mêmes cas que `test_music_level_reads_the_volume_percent_of_the_music_step` (backend/tests/test_montage.py).
describe("musicVolume", () => {
  it.each([
    [undefined, DEFAULT_MUSIC_VOLUME],
    [null, DEFAULT_MUSIC_VOLUME],
    [40, 40],
    ["25", 25],
    [0, 0],
    [250, 100],
    [-5, 0],
    ["fort", DEFAULT_MUSIC_VOLUME],
  ])("volume %s → %s %%", (volume, expected) => {
    expect(musicVolume({ volume })).toBe(expected);
  });

  it("vaut le défaut sans paramètres", () => {
    expect(musicVolume(undefined)).toBe(DEFAULT_MUSIC_VOLUME);
  });
});

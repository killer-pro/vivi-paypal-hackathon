import { useEffect, useState } from "react";
import type { Asset } from "../api";

/** Durées déjà lues, par asset (un asset ne change jamais : une régénération en crée un nouveau), et lectures en cours
 *  (un média illisible reste en cours : il n'est pas relu à chaque rendu). */
const known = new Map<number, number>();
const pending = new Set<number>();
const listeners = new Set<() => void>();

function probe(asset: Pick<Asset, "id" | "url" | "kind">) {
  pending.add(asset.id);
  const media = document.createElement(asset.kind === "voice" ? "audio" : "video");
  media.preload = "metadata";
  media.onloadedmetadata = () => {
    if (Number.isFinite(media.duration)) known.set(asset.id, media.duration);
    pending.delete(asset.id);
    listeners.forEach((notify) => notify());
  };
  media.src = asset.url;
}

/**
 * Durée (secondes) des clips et voix donnés, lue dans leurs métadonnées par le navigateur ; absente tant qu'elle n'est
 * pas connue. Sert à caler l'aperçu comme le montage, sans appel supplémentaire à l'API. Le composant se redessine à
 * chaque durée lue ; la table renvoyée est partagée et ne se modifie pas.
 */
export function useMediaDurations(assets: Pick<Asset, "id" | "url" | "kind">[]): ReadonlyMap<number, number> {
  const [, setVersion] = useState(0);
  useEffect(() => {
    const notify = () => setVersion((v) => v + 1);
    listeners.add(notify);
    return () => void listeners.delete(notify);
  }, []);
  useEffect(() => {
    for (const asset of assets) if (!known.has(asset.id) && !pending.has(asset.id)) probe(asset);
  });
  return known;
}

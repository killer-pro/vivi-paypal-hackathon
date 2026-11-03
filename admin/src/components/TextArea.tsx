import { useId, useImperativeHandle, useLayoutEffect, useRef, type ComponentProps } from "react";

/** Hauteur au-delà de laquelle la zone cesse de grandir et défile (part de la fenêtre). */
const MAX_HEIGHT_VH = 0.6;

type Props = Omit<ComponentProps<"textarea">, "value"> & { value: string };

/**
 * Zone de saisie qui s'agrandit avec son contenu (jusqu'à 60 % de la hauteur de la fenêtre, puis elle défile). Avec
 * `maxLength`, un compteur s'affiche dessous et passe au rouge quand la limite est atteinte.
 */
export default function TextArea({ value, maxLength, className = "input", ref, ...rest }: Props) {
  const field = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => field.current!);
  const counterId = useId();

  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    const resize = () => {
      el.style.height = "auto";
      const max = window.innerHeight * MAX_HEIGHT_VH;
      el.style.height = `${Math.min(el.scrollHeight + el.offsetHeight - el.clientHeight, max)}px`;
      el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
    };
    resize();
    const observer = new ResizeObserver(resize); // largeur modifiée (panneau redimensionné) : les retours à la ligne changent
    observer.observe(el);
    return () => observer.disconnect();
  }, [value]);

  const full = maxLength !== undefined && value.length >= maxLength;
  return (
    <div className="textarea">
      <textarea
        {...rest}
        ref={field}
        className={className}
        value={value}
        maxLength={maxLength}
        aria-describedby={maxLength === undefined ? rest["aria-describedby"] : counterId}
      />
      {maxLength !== undefined && (
        <span id={counterId} className={full ? "char-count is-full" : "char-count"}>
          {value.length} / {maxLength}
        </span>
      )}
    </div>
  );
}

import * as React from "react";

/** Delays invoking `fn` until `delay`ms after the last call — used to autosave editable content without a request per keystroke. */
export function useDebouncedCallback<A extends unknown[]>(fn: (...args: A) => void, delay = 500) {
  const fnRef = React.useRef(fn);
  fnRef.current = fn;
  const timer = React.useRef<ReturnType<typeof setTimeout>>(undefined);
  return React.useCallback(
    (...args: A) => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => fnRef.current(...args), delay);
    },
    [delay]
  );
}

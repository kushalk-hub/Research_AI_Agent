import { createContext, useContext, useLayoutEffect, useMemo, useReducer } from "react";
import { initialState, reducer } from "./reducer.js";

const StoreContext = createContext(null);
const DispatchContext = createContext(null);

const THEME_KEY = "fods.theme";

function initialTheme() {
  try {
    const stored = globalThis.localStorage?.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    /* storage can be unavailable; fall back to the system preference */
  }
  return "system";
}

export function StoreProvider({ children, preloaded = {} }) {
  const [state, dispatch] = useReducer(reducer, {
    ...initialState,
    theme: initialTheme(),
    ...preloaded,
  });

  // Theme is applied on <html data-theme>, never via an inline style attribute:
  // the served build runs under `style-src 'self'` and would block inline styles.
  // `data-theme-switching` disables colour transitions for one frame so a theme
  // change cannot show a half-faded, unreadable button.
  useLayoutEffect(() => {
    const root = globalThis.document?.documentElement;
    if (!root) return undefined;
    root.dataset.themeSwitching = "on";
    if (state.theme === "system") delete root.dataset.theme;
    else root.dataset.theme = state.theme;
    const timer = setTimeout(() => {
      delete root.dataset.themeSwitching;
    }, 200);
    try {
      globalThis.localStorage?.setItem(THEME_KEY, state.theme);
    } catch {
      /* ignore */
    }
    return () => clearTimeout(timer);
  }, [state.theme]);

  const value = useMemo(() => state, [state]);
  return (
    <DispatchContext.Provider value={dispatch}>
      <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
    </DispatchContext.Provider>
  );
}

export function useStore() {
  const state = useContext(StoreContext);
  if (!state) throw new Error("useStore must be used inside <StoreProvider>");
  return state;
}

export function useDispatch() {
  const dispatch = useContext(DispatchContext);
  if (!dispatch) throw new Error("useDispatch must be used inside <StoreProvider>");
  return dispatch;
}

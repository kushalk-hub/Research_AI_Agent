import { selectTurn } from "../store/selectors.js";
import EmptyThread from "./EmptyThread.jsx";
import Turn from "./Turn.jsx";

export default function Thread({ state, run, onFocusComposer, onOpenTrace }) {
  if (!run) return <EmptyThread onFocusComposer={onFocusComposer} />;
  const turn = selectTurn(state, run);
  return (
    <div className="thread-dock">
      <div className="thread">
        <Turn turn={turn} onOpenTrace={onOpenTrace} />
      </div>
    </div>
  );
}

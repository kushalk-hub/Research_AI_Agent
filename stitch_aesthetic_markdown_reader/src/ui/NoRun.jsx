/** Shown on Trace and Lab when no run is open. It explains what the page will
 *  contain instead of rendering an empty frame. */
export default function NoRun({ title, children, action }) {
  return (
    <div className="view-inner">
      <section className="panel no-run" aria-labelledby="no-run-title">
        <h2 id="no-run-title">{title}</h2>
        <p className="no-run-copy">{children}</p>
        {action && <div className="no-run-action">{action}</div>}
      </section>
    </div>
  );
}

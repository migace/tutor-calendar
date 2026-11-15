/** Placeholder shown while a page's first data loads. */
export function PageSkeleton({ label }: { label: string }) {
  return (
    <div aria-busy="true">
      <p className="visually-hidden" role="status">
        {label}
      </p>
      <div className="skeleton skeleton--title" />
      <div className="skeleton skeleton--row" />
      <div className="skeleton skeleton--row" />
    </div>
  );
}

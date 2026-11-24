export function auctionDetails(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const key of ["stock", "min_price_cents", "increment_cents"])
    data[key] = Number(data[key]);
  data.opens_at = new Date(data.opens_at).toISOString();
  data.closes_at = new Date(data.closes_at).toISOString();
  return data;
}

export function AuctionForm({ onSubmit, busy }) {
  return (
    <form className="create" onSubmit={onSubmit}>
      <label>
        Title
        <input name="title" required maxLength={160} />
      </label>
      <label>
        Stock
        <input name="stock" type="number" min="1" max="100000" defaultValue="3" required />
      </label>
      <label>
        Reserve (cents)
        <input name="min_price_cents" type="number" min="1" max="1000000000000" defaultValue="10000" required />
      </label>
      <label>
        Increment (cents)
        <input name="increment_cents" type="number" min="1" max="1000000000000" defaultValue="500" required />
      </label>
      <label>
        Opens (local time)
        <input name="opens_at" type="datetime-local" required />
      </label>
      <label>
        Closes (local time)
        <input name="closes_at" type="datetime-local" required />
      </label>
      <button disabled={busy}>Create auction</button>
    </form>
  );
}

import { useEffect, useId, useState } from "react";

const QR_SRC = "/wechat-qr.jpg";

export default function UpgradeContact({ email }: { email: string }) {
  const [open, setOpen] = useState(false);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <section className="mt-4 rounded-2xl border border-line bg-white p-5">
      <h2 className="text-base font-bold text-ink">开通付费</h2>
      <p className="mt-2 text-sm leading-6 text-ink/65">扫码加微信，备注登录邮箱 {email}。我确认后会帮你开通。</p>
      <button type="button" className="btn btn-primary mt-4" onClick={() => setOpen(true)}>
        开通付费
      </button>
      {open ? (
        <div className="fixed inset-0 z-40 grid place-items-center bg-ink/45 px-4" role="presentation" onClick={() => setOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="w-full max-w-sm rounded-2xl border border-line bg-white p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id={titleId} className="text-lg font-bold text-ink">
              微信扫码开通
            </h2>
            <p className="mt-2 text-sm leading-6 text-ink/65">备注登录邮箱 {email}</p>
            <img src={QR_SRC} alt="开通付费的微信二维码" className="mx-auto mt-4 h-64 w-64 rounded-xl border border-line object-contain" />
            <button type="button" className="btn btn-secondary mt-5 w-full" onClick={() => setOpen(false)}>
              关闭
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Copy, ExternalLink, MessageCircle, Unlink } from "lucide-react";
import { telegramConnectApi } from "../../../api/telegramConnectApi";
import { Button, Pill } from "../../../components/ui";

// My Profile: connect or disconnect the logged-in person's own Telegram.
// Same one-time link as Admin User Management; the backend decides whose
// profile it is from the session, so nothing here names a person.
export function MyTelegramPanel() {
  const [status, setStatus] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [code, setCode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const next = await telegramConnectApi.myStatus();
      setStatus(next);
      if (next.telegram_connected) setCode(null);
    } catch {
      // No employee profile (or no access): nothing to link, so no section.
      setHidden(true);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // After tapping Open Telegram the person comes back to this tab - check
  // then whether the Start went through, rather than asking them to reload.
  useEffect(() => {
    if (!code) return undefined;
    const onReturn = () => { if (document.visibilityState === "visible") refresh(); };
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [code, refresh]);

  async function connect() {
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      setCode(await telegramConnectApi.generateMyCode());
    } catch (err) {
      setError(err.message || "Could not create a Telegram link.");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(code.link || code.start_command);
      setCopied(true);
    } catch {
      setError("Could not copy - select the link and copy it manually.");
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Telegram from your SiteOps account? You'll stop getting SiteOps messages there until you connect again.")) return;
    setBusy(true);
    setError("");
    try {
      setStatus(await telegramConnectApi.unlinkMe());
    } catch (err) {
      setError(err.message || "Could not disconnect Telegram.");
    } finally {
      setBusy(false);
    }
  }

  if (hidden || !status) return null;
  const connected = status.telegram_connected;

  return <section className="rounded-[22px] border border-slate-200 bg-white p-4 sm:p-5">
    <div className="flex items-start gap-3">
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-blue-600 text-white"><MessageCircle size={19}/></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-black text-slate-950">Telegram</h2>
          {connected
            ? <Pill tone="blue">Connected{status.telegram_chat_hint ? ` · chat ${status.telegram_chat_hint}` : ""}</Pill>
            : <Pill tone="gray">Not connected</Pill>}
        </div>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          {connected
            ? "Your SiteOps account is linked to your Telegram. An admin decides when your messages switch to Telegram."
            : "Link your Telegram to receive SiteOps task and approval messages there."}
        </p>
        {error && <p className="mt-2 text-xs font-semibold text-rose-600">{error}</p>}

        {connected ? <Button type="button" variant="ghost" className="mt-3" loading={busy} onClick={disconnect}>
          <Unlink size={16}/>Disconnect Telegram
        </Button> : !code ? <Button type="button" className="mt-3" loading={busy} onClick={connect}>
          <MessageCircle size={16}/>Connect Telegram
        </Button> : <div className="mt-3 rounded-2xl border border-dashed border-blue-200 bg-blue-50/60 p-3">
          {code.link ? <>
            <p className="text-sm leading-6 text-slate-700">Open the SiteOps bot and tap <strong>Start</strong>. Then come back here.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button as="a" href={code.link} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/>Open Telegram</Button>
              <Button type="button" variant="secondary" onClick={copyLink}><Copy size={16}/>{copied ? "Copied" : "Copy link"}</Button>
            </div>
          </> : <>
            <p className="text-sm leading-6 text-slate-700">Open the SiteOps bot in Telegram and send this message:</p>
            <code className="mt-2 block break-all rounded-xl bg-white px-3 py-2 text-sm font-bold text-slate-900 shadow-sm">{code.start_command}</code>
            <Button type="button" variant="secondary" className="mt-2" onClick={copyLink}><Copy size={16}/>{copied ? "Copied" : "Copy"}</Button>
          </>}
          <p className="mt-2 text-xs font-semibold text-slate-500">Works once. Expires {new Date(code.expires_at).toLocaleTimeString("en-GB")}.</p>
          <Button type="button" variant="ghost" className="mt-1" loading={busy} onClick={connect}>Get a new link</Button>
        </div>}
      </div>
    </div>
  </section>;
}

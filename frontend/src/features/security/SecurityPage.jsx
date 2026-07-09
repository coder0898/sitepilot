import { useState } from "react";
import { authApi } from "../../api/authApi";
import { Card } from "../../components/ui";

export function SecurityPage({ action }) {
  const [token, setToken] = useState("");
  async function change(e) { e.preventDefault(); await action(() => authApi.changePassword(Object.fromEntries(new FormData(e.currentTarget))), "Password changed"); e.currentTarget.reset(); }
  async function forgot(e) { e.preventDefault(); const res = await authApi.requestReset(Object.fromEntries(new FormData(e.currentTarget))); setToken(res.token || res.message); }
  return <div className="stack"><Card><div className="panel-title"><div><p>Security</p><h2>Change password</h2></div></div><form className="smart-form" onSubmit={change}><input name="current_password" type="password" placeholder="Current password" /><input name="new_password" type="password" placeholder="New password" /><button>Change password</button></form></Card><Card><div className="panel-title"><div><p>Local reset</p><h2>Forgot password token</h2></div></div><form className="smart-form" onSubmit={forgot}><input name="email" placeholder="Email" /><button>Create token</button></form>{token && <div className="token-box"><code>{token}</code><button onClick={() => navigator.clipboard?.writeText(token)}>Copy token</button></div>}</Card></div>;
}

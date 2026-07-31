import { useEffect, useMemo, useState } from 'react';
import { vendorCategoryMappingApi } from '../../api/vendorCategoryMappingApi';

export function VendorCategoryMappingPage(){
  const [tasks,setTasks]=useState([]);
  const [vendors,setVendors]=useState([]);
  const [maps,setMaps]=useState([]);
  const [selected,setSelected]=useState({});
  const [loading,setLoading]=useState(true);
  const [message,setMessage]=useState('');
  const [filter,setFilter]=useState('all');

  async function load(){
    setLoading(true);
    try {
      const [t,v,m]=await Promise.all([
        vendorCategoryMappingApi.taskCategories(),
        vendorCategoryMappingApi.vendorCategories(),
        vendorCategoryMappingApi.mappings()
      ]);
      setTasks(t.items||t||[]);
      setVendors(v.items||v||[]);
      setMaps(m.items||m||[]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(()=>{load()},[]);

  const mapped = useMemo(
    ()=>new Map(maps.map(m=>[m.task_category_id,m.vendor_category_id])),
    [maps]
  );

  const rows = tasks.filter(t=>{
    if(filter==='mapped') return mapped.has(t.id);
    if(filter==='unmapped') return !mapped.has(t.id);
    return true;
  });

  async function confirmMap(id){
    if(!selected[id]) return;
    await vendorCategoryMappingApi.map({
      task_category_id:id,
      vendor_category_id:selected[id]
    });
    setMessage('Category mapping saved successfully');
    load();
  }

  async function unmap(id){
    await vendorCategoryMappingApi.unmap(id);
    setSelected({...selected,[id]:''});
    setMessage('Category mapping removed');
    load();
  }

  if(loading) return <div className="rounded-2xl bg-white p-6">Loading category mappings...</div>;

  const mappedCount = maps.length;
  const unmappedCount = tasks.length - mappedCount;

  return (
    <section className="space-y-5">
      <div className="rounded-2xl bg-white p-6 shadow-sm">
        <h2 className="text-xl font-semibold text-slate-900">Vendor Category Mapping</h2>
        <p className="mt-1 text-sm text-slate-500">Manage task category to vendor category mappings</p>

        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-xl bg-slate-50 p-4">
            <div className="text-sm text-slate-500">Total Categories</div>
            <div className="text-2xl font-semibold">{tasks.length}</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-4">
            <div className="text-sm text-slate-500">Mapped</div>
            <div className="text-2xl font-semibold">{mappedCount}</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-4">
            <div className="text-sm text-slate-500">Unmapped</div>
            <div className="text-2xl font-semibold">{unmappedCount}</div>
          </div>
        </div>
      </div>

      <div className="rounded-2xl bg-white p-6 shadow-sm">
        <div className="mb-4 flex flex-wrap gap-2">
          {['all','mapped','unmapped'].map(item=>(
            <button
              key={item}
              onClick={()=>setFilter(item)}
              className={`rounded-lg px-4 py-2 text-sm ${filter===item?'bg-blue-600 text-white':'bg-slate-100 text-slate-700'}`}
            >
              {item.charAt(0).toUpperCase()+item.slice(1)}
            </button>
          ))}
        </div>

        {message && <div className="mb-4 rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">{message}</div>}

        <div className="space-y-3">
          {rows.map(t=>{
            const current = selected[t.id] ?? mapped.get(t.id) ?? '';
            const isMapped = mapped.has(t.id);

            return (
              <div key={t.id} className="rounded-xl border border-slate-200 p-4 transition hover:shadow-sm">
                <div className="grid gap-4 md:grid-cols-4 md:items-center">
                  <div>
                    <div className="text-xs text-slate-500">Task Category</div>
                    <div className="font-medium text-slate-900">{t.name}</div>
                  </div>

                  <div>
                    <div className="text-xs text-slate-500">Vendor Category</div>
                    <select
                      value={current}
                      onChange={e=>setSelected({...selected,[t.id]:e.target.value})}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    >
                      <option value="">Select Vendor Category</option>
                      {vendors.map(v=>(
                        <option key={v.id} value={v.id}>{v.name}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <div className="text-xs text-slate-500">Status</div>
                    <span className={`mt-1 inline-flex rounded-full px-3 py-1 text-xs font-medium ${isMapped?'bg-green-100 text-green-700':'bg-yellow-100 text-yellow-700'}`}>
                      {isMapped?'Mapped':'Unmapped'}
                    </span>
                  </div>

                  <div className="flex gap-2 md:justify-end">
                    <button
                      disabled={!selected[t.id] || selected[t.id]===mapped.get(t.id)}
                      onClick={()=>confirmMap(t.id)}
                      className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
                    >
                      {isMapped?'Update':'Confirm'}
                    </button>
                    {isMapped && (
                      <button
                        onClick={()=>unmap(t.id)}
                        className="rounded-lg border border-red-200 px-4 py-2 text-sm text-red-600"
                      >
                        Unmap
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  );
}

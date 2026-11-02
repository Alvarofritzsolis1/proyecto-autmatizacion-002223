export type Profile={id:string;org_id:string;email:string;role:string}
export type Dashboard={documentos:number;procesados:number;en_cola:number;acreditados:number;revision:number;errores:number;contratistas:number}
export type Contractor={id:string;name:string;rut:string|null;created_at:string}
export type Evidence={pagina:number;motor:string;confianza_ocr:number|null;caracteres:number;extracto:string;tokens_muestra:Array<{text:string;bbox:number[];confidence?:number}>}
export type Document={
  id:string;original_name:string;mime_type:string;declared_type:string;detected_type:string|null;
  status:'queued'|'processing'|'complete'|'error';payment_status:string|null;
  page_count:number|null;extracted:{periodo?:string|null;ruts_validos?:string[];motores?:string[];verificacion_externa?:boolean};
  evidence:Evidence[];warnings:string[];error_message:string|null;created_at:string;updated_at:string;contractor_id:string|null
}
const base='/api/v1'
function csrf(){return document.cookie.split('; ').find(x=>x.startsWith('galant_csrf='))?.split('=')[1] || ''}
export async function api<T>(url:string,init:RequestInit={}):Promise<T>{
  const headers=new Headers(init.headers||{})
  if(init.body && !(init.body instanceof FormData))headers.set('Content-Type','application/json')
  if(!['GET','HEAD'].includes((init.method||'GET').toUpperCase()))headers.set('X-CSRF-Token',csrf())
  const r=await fetch(base+url,{...init,headers,credentials:'include',cache:'no-store'})
  if(!r.ok){let detail='Error HTTP '+r.status;try{const result=await r.json();if(typeof result.detail==='string')detail=result.detail}catch{}throw new Error(detail)}
  return r.json() as Promise<T>
}
export const auth={
  me:()=>api<Profile>('/auth/me'),
  login:(email:string,password:string)=>api<Profile>('/auth/login',{method:'POST',body:JSON.stringify({email,password})}),
  logout:()=>api<{ok:boolean}>('/auth/logout',{method:'POST'}),
}
export const dashboard=()=>api<Dashboard>('/dashboard')
export const documents={
  list:(type?:string)=>api<Document[]>('/documents'+(type?'?doc_type='+encodeURIComponent(type):'')),
  get:(id:string)=>api<Document>('/documents/'+encodeURIComponent(id)),
  upload:(file:File,type:string,contractorId:string)=>{
    const form=new FormData();form.append('file',file);form.append('doc_type',type)
    if(contractorId)form.append('contractor_id',contractorId)
    return api<Document>('/documents',{method:'POST',body:form})
  },
  retry:(id:string)=>api<Document>('/documents/'+encodeURIComponent(id)+'/retry',{method:'POST'}),
  fileUrl:(id:string)=>base+'/documents/'+encodeURIComponent(id)+'/file',
  reportUrl:(id:string)=>base+'/documents/'+encodeURIComponent(id)+'/report',
}
export const contractors={
  list:()=>api<Contractor[]>('/contractors'),
  create:(name:string,rut:string)=>api<Contractor>('/contractors',{method:'POST',body:JSON.stringify({name,rut:rut||null})}),
}

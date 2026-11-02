import {useEffect,useState,type ReactNode} from 'react'
import {Link,NavLink,Navigate,Route,Routes,useNavigate,useParams} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Activity,ArrowDownToLine,ArrowLeft,ArrowRight,BriefcaseBusiness,CheckCircle2,ChevronRight,
  CircleAlert,Clock3,CloudUpload,FileCheck2,FileClock,FileSearch2,Files,LayoutDashboard,
  LockKeyhole,LogOut,Menu,Moon,Plus,RefreshCcw,Search,ShieldCheck,Sun,Users,Zap} from 'lucide-react'
import {auth,contractors,dashboard,documents,type Contractor,type Document,type Profile} from './api'

const links=[
  {to:'overview',label:'Panel ejecutivo',icon:LayoutDashboard},
  {to:'documents',label:'Centro OCR',icon:FileSearch2},
  {to:'contributions',label:'Cotizaciones previsionales',icon:FileCheck2},
  {to:'f301',label:'Certificados F30-1',icon:Files},
  {to:'independent',label:'Trabajadores independientes',icon:Users},
  {to:'contractors',label:'Gestión de contratistas',icon:BriefcaseBusiness},
  {to:'history',label:'Historial y auditoría',icon:FileClock},
]
const types=[{id:'cotizaciones',title:'Cotizaciones previsionales',sub:'Previred y comprobantes'},
             {id:'f30_1',title:'Certificado F30-1',sub:'Análisis independiente'},
             {id:'independientes',title:'Trabajador independiente',sub:'Respaldo previsional'}]
const when=(v:string)=>new Date(v).toLocaleDateString('es-CL',{day:'2-digit',month:'short',year:'numeric'})
function state(d:Document){
  if(d.status==='queued')return 'En cola'
  if(d.status==='processing')return 'En procesamiento'
  if(d.status==='error')return 'Error de lectura'
  return d.payment_status || 'Analizado'
}
function kind(d:Document){
  if(d.status==='error')return 'error'
  if(d.status==='queued'||d.status==='processing')return 'info'
  if(d.payment_status==='Pago acreditado documentalmente')return 'ok'
  if(d.payment_status==='Pendiente de revisión')return 'warn'
  return 'neutral'
}
function Pill({doc}:{doc:Document}){return <span className={'pill '+kind(doc)}><span className="dot"/>{state(doc)}</span>}
function Empty({title,description}:{title:string;description:string}){return <div className="empty"><FileSearch2 size={34}/><h3>{title}</h3><p>{description}</p></div>}
function ErrorLine({error}:{error:Error|null}){return error?<div className="alert"><CircleAlert size={18}/>{error.message}</div>:null}
function Heading({eyebrow,title,description,action}:{eyebrow:string;title:string;description:string;action?:ReactNode}){return <header className="heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</header>}

function Login({onLogin}:{onLogin:(profile:Profile)=>void}){
  const[email,setEmail]=useState('');const[password,setPassword]=useState('')
  const mutation=useMutation({mutationFn:()=>auth.login(email,password),onSuccess:onLogin})
  return <div className="login"><section className="login-showcase"><div className="brand-row"><div className="brand-icon"><Zap size={21}/></div><div><strong>GALANT</strong><span>ENTERPRISE 2.0</span></div></div>
    <div className="login-hero"><span className="eyebrow">INTELIGENCIA DOCUMENTAL</span><h1>Tu operación documental, <em>en otro nivel.</em></h1>
      <p>Una plataforma para revisar cotizaciones, F30-1 y documentación de contratistas con trazabilidad de evidencia.</p>
      <div className="showcase-proof"><ShieldCheck size={19}/> OCR local · Datos privados · Resultados verificables</div></div>
    <div className="showcase-bottom">GALANT 2.0 · Plataforma web empresarial</div></section>
    <section className="login-form-wrap"><form className="login-form" onSubmit={e=>{e.preventDefault();mutation.mutate()}}>
      <div className="login-lock"><LockKeyhole size={24}/></div><span className="eyebrow">ACCESO PRIVADO</span><h2>Bienvenido a GALANT</h2>
      <p>Ingresa con tu cuenta autorizada para acceder al centro documental.</p>
      <label>Correo electrónico<input autoComplete="username" required type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="tu@empresa.cl"/></label>
      <label>Contraseña<input autoComplete="current-password" required type="password" value={password} onChange={e=>setPassword(e.target.value)}/></label>
      <ErrorLine error={mutation.error as Error|null}/>
      <button className="button primary full" disabled={mutation.isPending}>{mutation.isPending?'Verificando…':'Iniciar sesión'}<ArrowRight size={18}/></button>
      <p className="login-footer"><ShieldCheck size={16}/> Acceso restringido y protegido</p></form></section></div>
}

function Layout({profile,onLogout}:{profile:Profile;onLogout:()=>void}){
  const[mobile,setMobile]=useState(false);const[dark,setDark]=useState(()=>localStorage.getItem('galant-dark')==='1')
  useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light';localStorage.setItem('galant-dark',dark?'1':'0')},[dark])
  const logout=useMutation({mutationFn:auth.logout,onSettled:onLogout})
  const navigation=useNavigate()
  return <div className="shell"><aside className={'sidebar '+(mobile?'open':'')}>
    <div className="brand-row"><div className="brand-icon"><Zap size={19}/></div><div><strong>GALANT</strong><span>ENTERPRISE <b>2.0</b></span></div></div>
    <div className="workspace"><div className="workspace-letter">G</div><div><strong>Mi organización</strong><small>Espacio documental</small></div></div>
    <p className="sidebar-caption">ESPACIO DE TRABAJO</p>
    <nav>{links.map(item=><NavLink onClick={()=>setMobile(false)} className={({isActive})=>'nav-link '+(isActive?'active':'')} key={item.to} to={'/app/'+item.to}>
      <item.icon size={18}/><span>{item.label}</span></NavLink>)}{profile.role==='admin'&&<NavLink onClick={()=>setMobile(false)} className={({isActive})=>'nav-link '+(isActive?'active':'')} to="/app/monitor"><Activity size={18}/>Monitoreo técnico</NavLink>}</nav>
    <footer className="sidebar-bottom"><div className="sidebar-security"><ShieldCheck size={20}/><div><strong>Espacio protegido</strong><small>Procesamiento privado</small></div></div>
      <div className="user-profile"><div className="avatar">{profile.email.charAt(0).toUpperCase()}</div><div><strong>{profile.email.split('@')[0]}</strong><small>{profile.role==='admin'?'Administrador':profile.role==='analyst'?'Analista':'Consulta'}</small></div></div></footer>
  </aside>{mobile&&<div className="overlay" onClick={()=>setMobile(false)}/>}
  <section className="main"><header className="topbar"><div><button className="icon-button menu-button" onClick={()=>setMobile(true)}><Menu size={20}/></button><span className="breadcrumb">Workspace <ChevronRight size={15}/> <strong>GALANT 2.0</strong></span></div>
    <div className="top-actions"><span className="online"><span/> SISTEMA DOCUMENTAL</span><button className="icon-button" title="Cambiar tema" onClick={()=>setDark(!dark)}>{dark?<Sun size={19}/>:<Moon size={19}/>}</button>
      <button className="icon-button" title="Cerrar sesión" onClick={()=>logout.mutate()}><LogOut size={19}/></button><div className="mini-avatar">{profile.email.charAt(0).toUpperCase()}</div></div></header>
    <main className="content"><Routes>
      <Route path="overview" element={<Overview/>}/><Route path="documents" element={<Center/>}/>
      <Route path="contributions" element={<Center filter="cotizaciones"/>}/><Route path="f301" element={<Center filter="f30_1"/>}/>
      <Route path="independent" element={<Center filter="independientes"/>}/><Route path="contractors" element={<ContractorPage profile={profile}/>}/>
      <Route path="history" element={<History/>}/><Route path="monitor" element={profile.role==='admin'?<Monitor/>:<Navigate to="/app/overview"/>}/>
      <Route path="documents/:id" element={<Details/>}/><Route path="*" element={<Navigate to="/app/overview"/>}/>
    </Routes></main><button className="floating-add" title="Nuevo análisis" onClick={()=>navigation('/app/documents')}><Plus size={22}/></button></section></div>
}

function Overview(){
  const {data:stats,error}=useQuery({queryKey:['stats'],queryFn:dashboard,refetchInterval:5000})
  const {data:docs=[]}=useQuery({queryKey:['documents'],queryFn:()=>documents.list(),refetchInterval:5000})
  const metrics=[{title:'Documentos procesados',value:stats?.procesados||0,icon:Files},
                 {title:'Pagos acreditados documentalmente',value:stats?.acreditados||0,icon:FileCheck2},
                 {title:'Pendientes de revisión',value:stats?.revision||0,icon:Clock3},
                 {title:'Contratistas registrados',value:stats?.contratistas||0,icon:BriefcaseBusiness}]
  return <><Heading eyebrow="GESTIÓN DOCUMENTAL" title="Centro de control" description="Indicadores calculados con los datos reales de tu organización." action={<Link className="button primary" to="/app/documents"><CloudUpload size={18}/> Analizar documento</Link>}/>
    <ErrorLine error={error as Error|null}/><div className="metrics">{metrics.map(m=><div className="metric" key={m.title}><div className="metric-head"><span>{m.title}</span><m.icon size={20}/></div><strong>{m.value.toLocaleString('es-CL')}</strong><small>Datos actualizados automáticamente</small></div>)}</div>
    <div className="two-columns"><section className="panel"><div className="panel-head"><div><h2>Documentos recientes</h2><p>Estado de tus últimas revisiones</p></div><Link to="/app/history">Ver todo <ArrowRight size={16}/></Link></div>
      <DocumentTable docs={docs.slice(0,7)}/></section><section className="panel quick-panel"><h2>Comenzar un análisis</h2><p>Selecciona una categoría y sube tu documento.</p>
      {types.map(item=><Link className="quick-link" key={item.id} to={'/app/'+(item.id==='cotizaciones'?'contributions':item.id==='f30_1'?'f301':'independent')}><FileSearch2 size={19}/><span><strong>{item.title}</strong><small>{item.sub}</small></span><ChevronRight size={18}/></Link>)}
      <div className="notice"><CircleAlert size={18}/> Los resultados muestran evidencia documental; no validación externa de pagos.</div></section></div>
  </>
}

function DocumentTable({docs}:{docs:Document[]}){
  if(!docs.length)return <Empty title="Sin documentos todavía" description="Carga el primer archivo para comenzar tu análisis."/>
  return <div className="table-scroll"><table><thead><tr><th>Documento</th><th>Tipo</th><th>Fecha</th><th>Estado</th><th/></tr></thead><tbody>{docs.map(d=><tr key={d.id}><td><div className="file-name"><FileSearch2 size={18}/><span title={d.original_name}>{d.original_name}</span></div></td>
    <td>{d.declared_type==='f30_1'?'F30-1':d.declared_type==='independientes'?'Independiente':'Cotizaciones'}</td><td>{when(d.created_at)}</td>
    <td><Pill doc={d}/></td><td><Link className="row-link" to={'/app/documents/'+d.id}><ArrowRight size={17}/></Link></td></tr>)}</tbody></table></div>
}

function Center({filter}:{filter?:string}){
  const query=useQuery({queryKey:['documents',filter],queryFn:()=>documents.list(filter),refetchInterval:4000})
  const qc=useQueryClient()
  const mutation=useMutation({mutationFn:({file,type,contractorId}:{file:File;type:string;contractorId:string})=>documents.upload(file,type,contractorId),
    onSuccess:()=>{qc.invalidateQueries({queryKey:['documents']});qc.invalidateQueries({queryKey:['stats']});setFile(null)}})
  const[type,setType]=useState(filter||'cotizaciones')
  const[contractorId,setContractorId]=useState('')
  const[file,setFile]=useState<File|null>(null)
  const[drag,setDrag]=useState(false)
  const[search,setSearch]=useState('')
  const navigate=useNavigate()
  const {data:contractorList=[]}=useQuery({queryKey:['contractors'],queryFn:contractors.list})
  useEffect(()=>setType(filter||'cotizaciones'),[filter])
  const title=filter==='f30_1'?'Certificados F30-1':filter==='independientes'?'Trabajadores independientes':filter==='cotizaciones'?'Cotizaciones previsionales':'Centro de análisis OCR'
  const filtered=(query.data||[]).filter(d=>d.original_name.toLowerCase().includes(search.toLowerCase()))
  return <><Heading eyebrow="INTELIGENCIA DE DOCUMENTOS" title={title} description="Carga y analiza PDF digitales, escaneados e híbridos con trazabilidad."/>
    <div className="upload-panel panel"><div className="upload-header"><div><span className="eyebrow">NUEVO PROCESAMIENTO</span><h2>Analizar documento</h2></div><span className="small-mark"><ShieldCheck size={15}/> Archivo privado</span></div>
      <div className="upload-options">{types.filter(t=>!filter||t.id===filter).map(t=><button key={t.id} className={'type-card '+(type===t.id?'chosen':'')} onClick={()=>setType(t.id)}>
        <FileCheck2 size={20}/><span><strong>{t.title}</strong><small>{t.sub}</small></span></button>)}</div>
      <div className={'dropzone '+(drag?'dragging':'')} onDragEnter={e=>{e.preventDefault();setDrag(true)}} onDragLeave={e=>{e.preventDefault();setDrag(false)}}
        onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();setDrag(false);setFile(e.dataTransfer.files[0]||null)}}>
        <CloudUpload size={32}/><h3>{file?file.name:'Arrastra tu documento aquí'}</h3><p>PDF, PNG, JPG o TIFF · Máximo 25 MB · Hasta 50 páginas PDF</p>
        <label className="button secondary">Seleccionar archivo<input hidden type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" onChange={e=>setFile(e.target.files?.[0]||null)}/></label></div>
      <div className="upload-footer"><label>Asociar a contratista (opcional)<select value={contractorId} onChange={e=>setContractorId(e.target.value)}><option value="">Sin contratista</option>{contractorList.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
        <button className="button primary" disabled={!file||mutation.isPending} onClick={()=>file&&mutation.mutate({file,type,contractorId},{onSuccess:doc=>navigate('/app/documents/'+doc.id)})}>
          {mutation.isPending?'Enviando…':'Iniciar análisis OCR'}<ArrowRight size={18}/></button></div><ErrorLine error={mutation.error as Error|null}/></div>
    <div className="panel list-panel"><div className="panel-head"><div><h2>Documentos del módulo</h2><p>Historial de procesos y resultados</p></div><label className="search"><Search size={18}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Buscar documento"/></label></div>
      <ErrorLine error={query.error as Error|null}/><DocumentTable docs={filtered}/></div></>
}

function Details(){
  const{id}=useParams<{id:string}>()
  const[page,setPage]=useState(1)
  const qc=useQueryClient()
  const {data:doc,error}=useQuery({queryKey:['doc',id],queryFn:()=>documents.get(id||''),enabled:!!id,refetchInterval:4000})
  const retry=useMutation({mutationFn:()=>documents.retry(id||''),onSuccess:()=>{qc.invalidateQueries({queryKey:['doc',id]});qc.invalidateQueries({queryKey:['documents']})}})
  if(error)return <ErrorLine error={error as Error}/>
  if(!doc)return <div className="loading"><RefreshCcw className="spin" size={23}/> Cargando documento…</div>
  const evidence=doc.evidence.find(item=>item.pagina===page)
  return <><div className="detail-nav"><Link to="/app/history"><ArrowLeft size={17}/> Volver al historial</Link><div className="detail-actions">
    {doc.status==='complete'&&<a className="button secondary" href={documents.reportUrl(doc.id)}><ArrowDownToLine size={17}/> Exportar Excel</a>}
    {(doc.status==='error'||doc.status==='complete')&&<button className="button secondary" onClick={()=>retry.mutate()} disabled={retry.isPending}><RefreshCcw size={17}/> Reprocesar</button>}</div></div>
    <Heading eyebrow="RESULTADO DE ANÁLISIS" title={doc.original_name} description={'Documento cargado el '+when(doc.created_at)}/>
    <div className="detail-stats"><div><span>ESTADO</span><Pill doc={doc}/></div><div><span>PERÍODO</span><strong>{doc.extracted.periodo||'Sin identificar'}</strong></div>
      <div><span>PÁGINAS</span><strong>{doc.page_count||'—'}</strong></div><div><span>MOTORES</span><strong>{doc.extracted.motores?.join(', ')||'Pendiente'}</strong></div></div>
    {doc.status==='queued'||doc.status==='processing'?<div className="panel processing"><RefreshCcw className="spin" size={31}/><h2>{doc.status==='queued'?'Esperando procesamiento':'Analizando documento'}</h2><p>El motor OCR se ejecuta en el servidor y actualiza este resultado automáticamente.</p></div>:
      <div className="detail-columns"><section className="panel pdf-panel"><div className="panel-head"><div><h2>Documento original</h2><p>Contrasta la evidencia con el archivo</p></div>
        {doc.page_count&&<div className="page-selector"><button disabled={page===1} onClick={()=>setPage(p=>p-1)}>‹</button>{page} / {doc.page_count}<button disabled={page>=doc.page_count} onClick={()=>setPage(p=>p+1)}>›</button></div>}</div>
        <div className="pdf-viewer">{doc.mime_type==='application/pdf'?<iframe title="PDF original" key={page} src={documents.fileUrl(doc.id)+'#page='+page+'&toolbar=0'}/>:<img src={documents.fileUrl(doc.id)} alt="Documento original"/>}</div></section>
      <div className="detail-right"><section className="panel insight"><h2>Interpretación documental</h2><div className="fact"><span>Estado del respaldo</span><strong>{doc.payment_status||'No disponible'}</strong></div>
        <div className="fact"><span>Período</span><strong>{doc.extracted.periodo||'Sin identificar'}</strong></div>
        <div className="fact"><span>RUT válidos detectados</span><strong>{doc.extracted.ruts_validos?.join(', ')||'No detectados'}</strong></div>
        <div className="notice"><CircleAlert size={18}/> No se ha verificado el pago ante Previred, AFP ni autoridades.</div></section>
      <section className="panel insight"><h2>Observaciones</h2>{doc.error_message&&<div className="alert">{doc.error_message}</div>}
        {doc.warnings.length?doc.warnings.map((item,i)=><p className="observation" key={i}><CircleAlert size={16}/>{item}</p>):<p className="quiet"><CheckCircle2 size={16}/> Sin alertas técnicas adicionales</p>}</section>
      <section className="panel insight"><h2>Evidencia de página {page}</h2><div className="fact"><span>Método de lectura</span><strong>{evidence?.motor||'Sin datos'}</strong></div>
        <div className="fact"><span>Confianza OCR</span><strong>{evidence?.confianza_ocr===null||!evidence?'No aplica':evidence.confianza_ocr+'%'}</strong></div>
        <pre className="evidence">{evidence?.extracto||'Sin texto extraído'}</pre></section></div></div>}
    <ErrorLine error={retry.error as Error|null}/></>
}

function ContractorPage({profile}:{profile:Profile}){
  const qc=useQueryClient();const [name,setName]=useState('');const[rut,setRut]=useState('')
  const list=useQuery({queryKey:['contractors'],queryFn:contractors.list})
  const create=useMutation({mutationFn:()=>contractors.create(name,rut),onSuccess:()=>{setName('');setRut('');qc.invalidateQueries({queryKey:['contractors']});qc.invalidateQueries({queryKey:['stats']})}})
  return <><Heading eyebrow="ADMINISTRACIÓN" title="Gestión de contratistas" description="Empresas y personas vinculadas a la revisión documental."/>
    {profile.role!=='viewer'&&<form className="panel contractor-form" onSubmit={e=>{e.preventDefault();create.mutate()}}><h2>Registrar contratista</h2>
      <div className="form-row"><label>Nombre o razón social<input required minLength={2} maxLength={250} value={name} onChange={e=>setName(e.target.value)} placeholder="Constructora ejemplo SpA"/></label>
      <label>RUT (opcional)<input value={rut} onChange={e=>setRut(e.target.value)} placeholder="12.345.678-5"/></label>
      <button className="button primary" disabled={create.isPending}><Plus size={17}/> Agregar</button></div><ErrorLine error={create.error as Error|null}/></form>}
    <section className="panel list-panel"><div className="panel-head"><div><h2>Contratistas registrados</h2><p>{list.data?.length||0} registros</p></div></div>
      <ErrorLine error={list.error as Error|null}/>{list.data?.length?<div className="contractor-grid">{list.data.map((c:Contractor)=><div className="contractor-item" key={c.id}><div className="contractor-avatar">{c.name.charAt(0)}</div><div><strong>{c.name}</strong><small>{c.rut||'Sin RUT'} · {when(c.created_at)}</small></div></div>)}</div>:
      <Empty title="No existen contratistas" description="Registra contratistas para asociar documentos y períodos."/>}</section></>
}

function History(){
  const query=useQuery({queryKey:['documents'],queryFn:()=>documents.list(),refetchInterval:6000})
  return <><Heading eyebrow="TRAZABILIDAD" title="Historial de análisis" description="Consulta documentos procesados y sus resultados históricos."/>
    <section className="panel list-panel"><ErrorLine error={query.error as Error|null}/><DocumentTable docs={query.data||[]}/></section></>
}
function Monitor(){
  const query=useQuery({queryKey:['stats'],queryFn:dashboard,refetchInterval:3000})
  return <><Heading eyebrow="ADMINISTRACIÓN TÉCNICA" title="Monitoreo" description="Indicadores operativos de procesamiento y fallos."/>
    <div className="metrics"><div className="metric"><span>Trabajos en cola</span><strong>{query.data?.en_cola||0}</strong></div>
      <div className="metric"><span>Errores registrados</span><strong>{query.data?.errores||0}</strong></div>
      <div className="metric"><span>Documentos recibidos</span><strong>{query.data?.documentos||0}</strong></div></div>
    <p className="notice standalone"><ShieldCheck size={18}/> El monitoreo de memoria y CPU debe consultarse en el VPS.</p></>
}
export default function App(){
  const[profile,setProfile]=useState<Profile|null>(null)
  const {isPending}=useQuery({queryKey:['me'],queryFn:async()=>{try{const p=await auth.me();setProfile(p);return p}catch{setProfile(null);return null}},retry:false,staleTime:Infinity})
  if(isPending)return <div className="loading full-page"><RefreshCcw className="spin" size={24}/> Inicializando GALANT 2.0</div>
  return <Routes>{profile?<><Route path="/app/*" element={<Layout profile={profile} onLogout={()=>setProfile(null)}/>}/><Route path="*" element={<Navigate to="/app/overview"/>}/></>:
    <><Route path="/login" element={<Login onLogin={setProfile}/>}/><Route path="*" element={<Navigate to="/login"/>}/></>}</Routes>
}

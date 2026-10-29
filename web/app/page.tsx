"use client";

import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";
import { createClient, type User } from "@supabase/supabase-js";

type DocumentType = "cotizaciones" | "f30_1";
type DocStatus = "pendiente" | "procesando" | "completado" | "requiere_revision" | "error";
type Evidence = {
  pagina?: number;
  folio?: string;
  institucion?: string;
  periodo?: string;
  fecha_pago?: string;
  estado?: string;
  observacion?: string;
};
type Analysis = {
  comprobantes?: Evidence[];
  periodo?: string;
  estado_declarado?: string;
  cobertura?: string;
  paginas?: number;
  observacion?: string;
};
type DocumentRecord = {
  id: string;
  archivo: string;
  tipo: DocumentType;
  estado: DocStatus;
  created_at: string;
  resultado: Analysis | null;
  error?: string | null;
};

const endpoint = process.env.NEXT_PUBLIC_SUPABASE_URL;
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
const db = endpoint && publishableKey
  ? createClient(endpoint, publishableKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    })
  : null;

const bucket = "galant-documentos";
const maxPerPdf = 25 * 1024 * 1024;
const maxBatch = 20;
const maxBatchBytes = 60 * 1024 * 1024;

function humanDate(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : new Intl.DateTimeFormat("es-CL", {
    dateStyle: "short", timeStyle: "short",
  }).format(date);
}

function statusName(status: DocStatus) {
  const labels: Record<DocStatus, string> = {
    pendiente: "Pendiente de OCR",
    procesando: "Procesando",
    completado: "Analizado",
    requiere_revision: "Requiere revisión",
    error: "Error de lectura",
  };
  return labels[status];
}

function getFirstValue(doc: DocumentRecord, name: "periodo" | "fecha_pago") {
  const evidence = doc.resultado?.comprobantes ?? [];
  const values = Array.from(new Set(evidence.map((x) => x[name]).filter(Boolean)));
  if (values.length === 0) return name === "periodo" ? (doc.resultado?.periodo || "—") : "—";
  return values.length === 1 ? String(values[0]) : "Varios";
}

function statusDocumental(doc: DocumentRecord) {
  if (doc.estado !== "completado" && doc.estado !== "requiere_revision") return "—";
  if (doc.tipo === "f30_1") return doc.resultado?.estado_declarado || "Declaración por revisar";
  const receipts = doc.resultado?.comprobantes ?? [];
  if (receipts.length === 0) return "Sin respaldo suficiente";
  const relevant = receipts.filter((r) => Boolean(r.fecha_pago && r.periodo));
  if (relevant.length === 0) return "Datos insuficientes";
  if (doc.estado === "requiere_revision") return "Respaldo parcial; revisar";
  return "Respaldo documental encontrado";
}

function Icon({ name, size = 20 }: { name: "shield" | "file" | "database" | "clock"; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "shield") return <svg {...common}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>;
  if (name === "file") return <svg {...common}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>;
  if (name === "database") return <svg {...common}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 2 4 3 9 3s9-1 9-3V5M3 12c0 2 4 3 9 3s9-1 9-3"/></svg>;
  return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
}

export default function Page() {
  const [user, setUser] = useState<User | null>(null);
  const [initialized, setInitialized] = useState(false);
  const [email, setEmail] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selection, setSelection] = useState<string>("todos");

  const refresh = useCallback(async () => {
    if (!db) return;
    const { data: { user: current }, error: authError } = await db.auth.getUser();
    if (authError || !current) {
      setDocuments([]);
      setUser(null);
      return;
    }
    const { data, error } = await db.from("galant_documentos")
      .select("id,archivo,tipo,estado,created_at,resultado,error")
      .order("created_at", { ascending: false })
      .limit(100);
    if (error) setInfo("No se pudo cargar el historial. Comprueba la migración SQL y permisos.");
    else setDocuments((data || []) as DocumentRecord[]);
  }, []);

  useEffect(() => {
    if (!db) {
      setInitialized(true);
      return;
    }
    const client = db;
    let mounted = true;
    void client.auth.getUser().then(({ data }) => {
      if (!mounted) return;
      setUser(data.user);
      setInitialized(true);
      if (data.user) void refresh();
    });
    const { data: { subscription } } = client.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      setUser(session?.user ?? null);
      if (!session?.user) setDocuments([]);
      else void refresh();
    });
    return () => { mounted = false; subscription.unsubscribe(); };
  }, [refresh]);

  const counts = useMemo(() => ({
    uploaded: documents.length,
    completed: documents.filter((x) => x.estado === "completado").length,
    review: documents.filter((x) => x.estado === "requiere_revision" || x.estado === "error").length,
    pending: documents.filter((x) => x.estado === "pendiente" || x.estado === "procesando").length,
  }), [documents]);

  const filtered = useMemo(() => selection === "todos"
    ? documents
    : documents.filter((d) => selection === "revisar"
      ? d.estado === "requiere_revision" || d.estado === "error"
      : d.tipo === selection), [documents, selection]);

  async function signIn(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!db) return;
    setBusy(true);
    setInfo("");
    try {
      const { error } = await db.auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: window.location.origin },
      });
      setInfo(error ? "No se pudo solicitar el acceso: " + error.message : "Revisa tu correo para ingresar a GALANT.");
    } finally { setBusy(false); }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>, tipo: DocumentType) {
    if (!db || !user || busy) return;
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    if (files.length > maxBatch || files.reduce((n, f) => n + f.size, 0) > maxBatchBytes) {
      setInfo("Máximo 20 documentos o 60 MB por carga.");
      return;
    }
    setBusy(true);
    let done = 0;
    const problems: string[] = [];
    try {
      for (const file of files) {
        setInfo("Cargando " + (done + 1) + " de " + files.length + ": " + file.name);
        if (file.size > maxPerPdf || !file.name.toLowerCase().endsWith(".pdf")) {
          problems.push(file.name + ": debe ser un PDF de máximo 25 MB.");
          continue;
        }
        if (await file.slice(0, 5).text() !== "%PDF-") {
          problems.push(file.name + ": el contenido no corresponde a un PDF válido.");
          continue;
        }
        const buffer = await file.arrayBuffer();
        const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", buffer)))
          .map((b) => b.toString(16).padStart(2, "0")).join("");
        const { data: existing, error: queryError } = await db.from("galant_documentos")
          .select("id").eq("sha256", hash).eq("tipo", tipo).limit(1);
        if (queryError) { problems.push(file.name + ": no se pudo verificar duplicado."); continue; }
        if (existing?.length) { problems.push(file.name + ": ya existe en tu historial."); continue; }

        const id = crypto.randomUUID();
        const storagePath = user.id + "/" + id + ".pdf";
        const uploadResult = await db.storage.from(bucket).upload(storagePath, file, {
          cacheControl: "0", contentType: "application/pdf", upsert: false,
        });
        if (uploadResult.error) {
          problems.push(file.name + ": " + uploadResult.error.message);
          continue;
        }
        const saved = await db.from("galant_documentos").insert({
          id, usuario_id: user.id, archivo: file.name.slice(0, 255),
          tipo, ruta_storage: storagePath, sha256: hash,
        });
        if (saved.error) {
          await db.storage.from(bucket).remove([storagePath]);
          problems.push(file.name + ": no se registró la carga (" + saved.error.message + ").");
        } else done += 1;
      }
      setInfo(
        done + " documento(s) guardado(s) de forma privada. "
        + "El análisis comenzará cuando esté conectado el trabajador Python."
        + (problems.length ? " Observaciones: " + problems.join(" | ") : "")
      );
      await refresh();
    } catch (error) {
      setInfo("La carga no pudo terminar: " + (error instanceof Error ? error.message : "error desconocido"));
    } finally { setBusy(false); }
  }

  if (!db) {
    return <main className="shell"><section className="notice"><h1>GALANT</h1><h2>Conexión de base de datos pendiente</h2><p>Configura NEXT_PUBLIC_SUPABASE_URL y NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY en el proyecto de Vercel. No agregues claves secretas al navegador.</p></section></main>;
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><div className="brand-icon"><Icon name="shield" size={22}/></div><div><strong>GALANT</strong><small>Control documental inteligente</small></div></div>
        <div className="top-actions"><span className="online"><span className="online-dot"/> Entorno privado</span>{user && <button className="outline-btn" type="button" onClick={() => { void db.auth.signOut(); }}>Cerrar sesión</button>}</div>
      </header>
      {!initialized ? <section className="loading">Cargando sesión segura…</section> : !user ? (
        <section className="login-wrap">
          <div className="login-copy"><span className="eyebrow">Plataforma GALANT</span><h1>Documentos bajo control. <em>Sin complicaciones.</em></h1><p>Analiza cotizaciones previsionales y certificados F30-1 en un espacio privado. Organiza las fechas, los períodos y las observaciones en un solo lugar.</p><div className="trust-row"><Icon name="shield" size={19}/> Acceso personalizado y archivos no públicos</div></div>
          <form className="login-card" onSubmit={(e) => { void signIn(e); }}><div className="small-illustration"><Icon name="file" size={24}/></div><h2>Ingresar a GALANT</h2><p>Recibirás un enlace de acceso en tu correo electrónico.</p><label htmlFor="email">Correo electrónico</label><input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="correo@empresa.cl" autoComplete="email"/><button className="primary-btn" disabled={busy}>Enviar enlace seguro</button>{info && <div className="message" role="status">{info}</div>}</form>
        </section>
      ) : (
        <>
          <section className="hero"><div><div className="eyebrow">PANEL DE CONTROL DOCUMENTAL</div><h1>Una revisión más clara,<br/><span>desde un solo lugar.</span></h1><p>Identifica los respaldos de pago, fechas y períodos. Los análisis documentales no sustituyen la verificación oficial de las instituciones.</p></div><div className="hero-mark"><Icon name="shield" size={80}/></div></section>
          <div className="section-heading"><div><h2>Resumen de documentos</h2><p>Historial privado asociado a tu cuenta</p></div><button type="button" className="outline-btn" disabled={busy} onClick={() => { setInfo(""); void refresh(); }}>Actualizar resultados</button></div>
          <section className="stats"><div className="stat"><div className="stat-icon blue"><Icon name="file"/></div><span>Total de archivos</span><strong>{counts.uploaded}</strong></div><div className="stat"><div className="stat-icon green"><Icon name="database"/></div><span>Analizados</span><strong>{counts.completed}</strong></div><div className="stat"><div className="stat-icon amber"><Icon name="clock"/></div><span>Por revisar</span><strong>{counts.review}</strong></div><div className="stat"><div className="stat-icon gray"><Icon name="clock"/></div><span>En cola</span><strong>{counts.pending}</strong></div></section>
          <div className="section-heading uploads-title"><div><h2>Subir documentos</h2><p>Dos categorías independientes, como en GALANT V13</p></div><span className="helper">Hasta 20 PDF y 60 MB por carga</span></div>
          <section className="upload-grid">
            <div className="upload-card"><div className="upload-icon"><Icon name="file" size={26}/></div><h3>Pago de cotizaciones</h3><p>Previred, AFP, Fonasa, ISL y comprobantes previsionales. Se revisan pago, fecha y período.</p><label className={"upload-button" + (busy ? " disabled" : "")} htmlFor="cotizaciones">Seleccionar PDF de cotizaciones</label><input id="cotizaciones" disabled={busy} type="file" accept=".pdf,application/pdf" multiple onChange={(e) => { void upload(e, "cotizaciones"); }}/></div>
            <div className="upload-card"><div className="upload-icon"><Icon name="shield" size={26}/></div><h3>Certificados F30-1</h3><p>Certificados de cumplimiento laboral y previsional. Se leen de forma independiente de Previred.</p><label className={"upload-button secondary" + (busy ? " disabled" : "")} htmlFor="f301">Seleccionar certificados F30-1</label><input id="f301" disabled={busy} type="file" accept=".pdf,application/pdf" multiple onChange={(e) => { void upload(e, "f30_1"); }}/></div>
          </section>
          {info && <div className="message status-message" role="status">{info}</div>}
          <section className="data-section"><div className="section-heading"><div><h2>Revisiones y resultados</h2><p>Los documentos pendientes no significan cotizaciones impagas</p></div><div className="tabs" role="group" aria-label="Filtrar documentos">{[["todos","Todos"],["cotizaciones","Cotizaciones"],["f30_1","F30-1"],["revisar","Revisar"]].map(([id,label]) => <button key={id} type="button" className={selection === id ? "active" : ""} onClick={() => setSelection(id)}>{label}</button>)}</div></div>
            <div className="table-container"><table><thead><tr><th>Documento</th><th>Tipo</th><th>Período</th><th>Fecha pago</th><th>Estado</th><th>Evidencia</th></tr></thead><tbody>{filtered.map((row) => <tr key={row.id}><td><strong className="filename" title={row.archivo}>{row.archivo}</strong><span className="muted">{humanDate(row.created_at)}</span></td><td>{row.tipo === "f30_1" ? "F30-1" : "Cotizaciones"}</td><td>{getFirstValue(row, "periodo")}</td><td>{row.tipo === "f30_1" ? "—" : getFirstValue(row, "fecha_pago")}</td><td><span className={"status " + row.estado}>{statusName(row.estado)}</span></td><td><span className="evidence-text">{statusDocumental(row)}</span>{row.resultado?.comprobantes?.length ? <details className="receipt-details"><summary>Ver {row.resultado.comprobantes.length} comprobante(s)</summary><ul>{row.resultado.comprobantes.map((item, i) => <li key={i}>Pág. {item.pagina ?? "?"} · {item.institucion || "Institución sin identificar"} · {item.periodo || "Período no identificado"} · {item.fecha_pago || "Fecha no identificada"} · {item.estado || "Revisar"} {item.observacion ? " · " + item.observacion : ""}</li>)}</ul></details> : null}{row.error && <p className="row-error">{row.error}</p>}</td></tr>)}{filtered.length === 0 && <tr><td colSpan={6}><div className="empty">Todavía no hay documentos en esta categoría.</div></td></tr>}</tbody></table></div>
          </section>
          <footer><Icon name="shield" size={16}/> GALANT · Respaldos documentales, no certificación de pago oficial. El análisis OCR requiere un trabajador Python configurado.</footer>
        </>
      )}
    </main>
  );
}

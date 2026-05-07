import { useEffect, useState } from "react";
import { api } from "../api/client";

export function LawsLibrary() {
  const [laws, setLaws] = useState<any[]>([]);
  const [mappings, setMappings] = useState<any[]>([]);
  const [identifier, setIdentifier] = useState("LC 214/2025");
  const [kind, setKind] = useState("LC");
  const [text, setText] = useState("");
  const [obsoleteRef, setObsoleteRef] = useState("PLP 68");
  const [vigentLawId, setVigentLawId] = useState<number | "">("");

  async function refresh() {
    setLaws(await api.listLaws());
    setMappings(await api.listMappings());
  }
  useEffect(() => {
    refresh();
  }, []);

  async function uploadLaw(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    fd.set("identifier", identifier);
    fd.set("kind", kind);
    if (text) fd.set("text", text);
    await api.uploadLaw(fd);
    setText("");
    await refresh();
  }

  async function addMapping() {
    if (!vigentLawId) return;
    await api.createMapping({
      obsolete_ref: obsoleteRef,
      vigent_law_id: Number(vigentLawId),
    });
    setObsoleteRef("");
    await refresh();
  }

  return (
    <div>
      <h2>Leis & Mapeamentos</h2>
      <p className="muted">
        Cadastre os textos das leis vigentes e o mapeamento PLP → LC. Esses
        dados ficam cacheados nas chamadas ao Claude.
      </p>

      <section>
        <h3>Cadastrar lei vigente</h3>
        <form onSubmit={uploadLaw}>
          <div className="row">
            <input
              placeholder="Identificador (ex.: LC 214/2025)"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
            />
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="LC">Lei Complementar</option>
              <option value="L">Lei Ordinária</option>
              <option value="EC">Emenda Constitucional</option>
              <option value="MP">Medida Provisória</option>
            </select>
          </div>
          <textarea
            placeholder="Cole o texto da lei aqui (ou envie PDF abaixo)"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
          />
          <div className="row">
            <input type="file" name="file" accept="application/pdf,text/plain" />
            <button type="submit" className="primary">
              Cadastrar
            </button>
          </div>
        </form>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Identificador</th>
              <th>Tipo</th>
            </tr>
          </thead>
          <tbody>
            {laws.map((l) => (
              <tr key={l.id}>
                <td>{l.id}</td>
                <td>{l.identifier}</td>
                <td>{l.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section style={{ marginTop: 32 }}>
        <h3>Mapeamentos PLP → Lei vigente</h3>
        <div className="row">
          <input
            placeholder="PLP 108"
            value={obsoleteRef}
            onChange={(e) => setObsoleteRef(e.target.value)}
          />
          <select
            value={vigentLawId}
            onChange={(e) =>
              setVigentLawId(e.target.value ? Number(e.target.value) : "")
            }
          >
            <option value="">Selecione a lei vigente</option>
            {laws.map((l) => (
              <option key={l.id} value={l.id}>
                {l.identifier}
              </option>
            ))}
          </select>
          <button onClick={addMapping} className="primary">
            Adicionar
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Obsoleto</th>
              <th>Vigente (id)</th>
            </tr>
          </thead>
          <tbody>
            {mappings.map((m) => (
              <tr key={m.id}>
                <td>{m.obsolete_ref}</td>
                <td>{m.vigent_law_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

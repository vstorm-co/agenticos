<!-- source_sha: 6ba9e8a85274 -->

# Contribuindo com o AgenticOS

[English](CONTRIBUTING.md) · [Polski](CONTRIBUTING.pl.md) · [Deutsch](CONTRIBUTING.de.md) · [Español](CONTRIBUTING.es.md) · **Português**

Obrigado pelo interesse. Este documento vai direto ao ponto e detalha especificamente
o que faz pull requests serem rejeitados.

## O padrão de qualidade

O código entra quando um mantenedor o aceitaria sem modificações. Concretamente:

- **Totalmente tipado.** Nada de `Any`, sem `# type: ignore`, sem blocos `except:` que façam
  um erro desaparecer. Modele com tipos precisos em vez de dicionários soltos.
- **Erros explícitos e ruidosos.** Falhe com uma mensagem clara; nunca engula uma exceção
  ou tente contornar um bug com fallbacks silenciosos. Uma resposta silenciosamente incorreta é pior do que uma falha explícita.
- **Sem peso morto.** Nada de abstrações especulativas, parâmetros não utilizados,
  código comentado ou ramificações "só por garantia".
- **Comentários explicam o *porquê*.** O que o código faz é visível; por que ele faz dessa
  forma não é, e é exatamente disso que um leitor precisará daqui a seis meses.
- **Respeite o código existente.** Os padrões e convenções dele prevalecem sobre preferências pessoais.

## Configurando o ambiente

```bash
make dev            # postgres, redis, api, worker, frontend
make seed           # uma organização, um proprietário, um perfil padrão de modelo
```

O backend precisa de uma chave `VAULT_MASTER_KEY`. Sem ela, ele utiliza a
`SECRET_KEY`, o que funciona localmente, mas é recusado em produção.

## Executando os testes

Consulte [`AGENTS.md`](AGENTS.md#testing) para ver as diretrizes completas. Em resumo:

```bash
make test               # backend, com o gate de cobertura de 100%
make test-frontend      # vitest unitário + integração, sem cobertura
make test-frontend-cov  # o mesmo, com o gate que o CI aplica
make test-e2e           # playwright
make check              # todas as etapas do CI exceto e2e — execute antes de abrir um PR
```

**`make test-frontend` não mede cobertura, e o único gate do frontend é um
limite de cobertura.** Ele é para desenvolvimento rápido; `make check` é a validação definitiva.

**A camada da plataforma é mantida sob 100% de cobertura** e o CI impõe essa regra. Isso inclui
`app/agents/`, o catálogo de permissões, o cofre (vault) e os serviços construídos sobre eles.
Subsistemas herdados de templates (o pipeline de RAG, conectores, adaptadores de canal)
são reportados, mas não bloqueiam o build — exigir o mesmo padrão de código legado resultaria em testes com excesso de mocks que compram apenas um número em vez de confiança real.

Se você adicionar um arquivo à camada da plataforma, ele precisará de testes que falhariam se o
comportamento mudasse. Testes que apenas cobrem o caminho feliz não são suficientes.

## Arquitetura em um parágrafo

Um agente é **dado**, não código. O `AgentSpec` é o contrato: o Builder o edita,
o banco de dados o versiona, `app/agents/factory.py` o instancia, e o
cliente pode comitá-lo em seu próprio repositório Git como YAML. Tudo de que um agente é
composto é uma **capacidade (capability)** — busca de conhecimento, navegação web, limite
orçamentário, conjunto de habilidades — declarada em código com metadados e composta por
configuração. A configuração só pode alcançar o que o código registrou.

Duas regras decorrem disso, e a maioria dos comentários de revisão volta a elas:

**Identificadores são permanentes.** O ID de uma capacidade aparece em especificações salvas e nos
repositórios dos clientes. Renomeie a classe Python livremente; alterar o ID é uma quebra de compatibilidade.

**Valide no momento da publicação, não em tempo de execução.** Um agente inválido deve ser recusado enquanto
o usuário olha para o formulário na UI, não às 3h da manhã em uma conversa com cliente.

## Adicionando uma capacidade (capability)

Uma pasta sob `app/agents/capabilities/`, espelhando a estrutura das demais:

```
app/agents/capabilities/seu_recurso/
    __init__.py        # registro + exportações públicas
    _capability.py     # subclasse de AbstractCapability
    _toolset.py        # suas ferramentas, se houver
    README.md          # decisões de design, não apenas descrição de código
```

Registre-a em `load_builtins()` dentro de `_registry.py`, caso contrário ela não existirá para
o Builder — esse acoplamento é intencional.

Se a capacidade puder agir sobre o mundo externo, marque-a com `side_effecting=True`.
Isso torna a aprovação humana obrigatória por padrão; esquecer essa flag é como um agente
acaba enviando e-mails sem supervisão.

## Pull requests

- Um assunto por PR. Um refactoring e uma feature em um único diff não serão revisados
  adequadamente.
- Correções de bugs devem acompanhar um teste de regressão que falha sem a correção.
- Explique o que você decidiu e por que na descrição do PR. O código mostra o *como*.

## Segurança

Não abra uma issue pública para relatar vulnerabilidades. Consulte [`SECURITY.md`](SECURITY.md).

## Licença

Ao contribuir, você concorda que seu trabalho será licenciado sob a Apache License
2.0, os mesmos termos do restante deste repositório. Não há necessidade de CLA.

from textwrap import dedent

 # Obtain a list of workflow templates. This can be filtered by the science group label.
workflows_templates_template = dedent('''query WorkflowTemplates {
    workflowTemplates(limit: 5, filter: {scienceGroup: IMAGING}) {
        nodes {
            name
            maintainer
            title
        }
    }
}
''')



# For a given visit, get a list of workflows. This can be filtered by creator, template and status.
filtered_workflows_templates_template = dedent('''query workflows {
  workflows(visit: {
    proposalCode: "mg"
    proposalNumber: 36964
    number: 1
  }
  limit: 10,
  filter: {
    creator: "gmg29649",
    template: "example-template",
  	workflowStatusFilter: {succeeded: true}
  }
  ){
    nodes {
      name
      status {__typename}
    }
  }
}
''')

# Obtain information about a specified workflow.
specified_workflow_template = dedent('''query Workflow {
    workflow(
        visit: { proposalCode: "mg", proposalNumber: 36964, number: 1 }
        name: "conditional-steps-tswxm"
    ) {
        name
        parameters
        templateRef
    		creator {creatorId}
    		status {__typename}
    }
}
''')


# Create a new workflow in the specified visit from an existing template.

submit_workflow_from_template_template = dedent('''mutation SubmitWorkflowFromTemplate {
    submitWorkflowTemplate(
        name: "example-template"
        visit: { proposalCode: "mg", proposalNumber: 36964, number: 1 }
        parameters: {png: "True", jpg: "False", jpeg: "True", tif: "True", tiff: "False"}
    ) {
        name
    }
}
''')

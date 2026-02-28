pipeline {
    agent any

    environment {
        // Path to the virtual environment relative to the Jenkins workspace
        VENV_BIN = "${WORKSPACE}/../.venv/bin"
        PYTHONPATH = "${WORKSPACE}/logflow"
    }

    stages {
        stage('Initialize') {
            steps {
                echo 'Initializing Workspace...'
                // Ensure the environment is set up (usually done by setup script)
                sh "${VENV_BIN}/pip install -e ./logflow[dev]"
            }
        }

        stage('Linting') {
            parallel {
                stage('Black') {
                    steps {
                        sh "${VENV_BIN}/black --check logflow"
                    }
                }
                stage('Isort') {
                    steps {
                        sh "${VENV_BIN}/isort --check-only logflow"
                    }
                }
                stage('Flake8') {
                    steps {
                        sh "${VENV_BIN}/flake8 logflow"
                    }
                }
            }
        }

        stage('Type Check') {
            steps {
                sh "${VENV_BIN}/mypy logflow"
            }
        }

        stage('Unit Tests') {
            steps {
                sh "${VENV_BIN}/pytest logflow/tests"
            }
        }
    }

    post {
        always {
            echo 'LogFlow Pipeline Complete.'
        }
        success {
            echo 'Project is healthy and ready for publication.'
        }
        failure {
            echo 'Build failed. Please check linting or test failures.'
        }
    }
}

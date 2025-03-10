import json
import os
import stat
import time
from pathlib import Path
from random import randint

from django.shortcuts import HttpResponse, redirect

from backup.backupManager import BackupManager
from loginSystem.models import Administrator
from loginSystem.views import loadLoginPage
from plogical.Backupsv2 import CPBackupsV2
from plogical.CyberCPLogFileWriter import CyberCPLogFileWriter as logging
from plogical.acl import ACLManager
from plogical.httpProc import httpProc
from plogical.processUtilities import ProcessUtilities as pu
from plogical.virtualHostUtilities import virtualHostUtilities as vhu
from websiteFunctions.models import Websites
from .IncBackupProvider import IncBackupProvider
from .IncBackupPath import IncBackupPath
from .IncBackupsControl import IncJobs
from .models import IncJob, BackupJob, JobSites




def def_renderer(request, templateName, args, context=None):
    proc = httpProc(request, templateName,
                    args, context)
    return proc.render()


def _get_destinations(local: bool = False):
    destinations = []
    if local:
        destinations.append('local')
    path = Path(IncBackupPath.SFTP.value)
    if path.exists():
        for item in path.iterdir():
            destinations.append('sftp:%s' % item.name)

    path = Path(IncBackupPath.AWS.value)
    if path.exists():
        for item in path.iterdir():
            destinations.append('s3:s3.amazonaws.com/%s' % item.name)
    return destinations


def _get_user_acl(request):
    user_id = request.session['userID']
    current_acl = ACLManager.loadedACL(user_id)
    return user_id, current_acl




def create_backup(request):

    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'createBackup') == 0:
            return ACLManager.loadError()

        websites = ACLManager.findAllSites(current_acl, user_id)

        destinations = _get_destinations(local=True)

        return def_renderer(request, 'IncBackups/createBackup.html',
                            {'websiteList': websites, 'destinations': destinations}, 'createBackup')
    except BaseException as msg:
        logging.writeToFile(str(msg))
        return redirect(loadLoginPage)


def backup_destinations(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'addDeleteDestinations') == 0:
            return ACLManager.loadError()

        return def_renderer(request, 'IncBackups/incrementalDestinations.html', {}, 'addDeleteDestinations')
    except BaseException as msg:
        logging.writeToFile(str(msg))
        return redirect(loadLoginPage)


def add_destination(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'addDeleteDestinations') == 0:
            return ACLManager.loadErrorJson('destStatus', 0)

        data = json.loads(request.body)

        if data['type'].lower() == IncBackupProvider.SFTP.name.lower():
            path = Path(IncBackupPath.SFTP.value)
            path.mkdir(exist_ok=True)

            ip_address = data['IPAddress']
            password = data['password']

            address_file = path / ip_address
            port = data.get('backupSSHPort', '22')

            if address_file.exists():
                final_dic = {'status': 0, 'error_message': 'This destination already exists.'}
                final_json = json.dumps(final_dic)
                return HttpResponse(final_json)

            python_path = Path('/usr/local/CyberCP/bin/python')
            backup_utils = Path(vhu.cyberPanel) / "plogical/backupUtilities.py"

            exec_args = "submitDestinationCreation --ipAddress %s --password %s --port %s --user %s" % \
                        (ip_address, password, port, 'root')

            exec_cmd = "%s %s %s" % (python_path, backup_utils, exec_args)

            if Path(pu.debugPath).exists():
                logging.writeToFile(exec_cmd)

            output = pu.outputExecutioner(exec_cmd)

            if Path(pu.debugPath).exists():
                logging.writeToFile(output)

            if output.find('1,') > -1:
                content = '%s\n%s' % (ip_address, port)
                with open(address_file, 'w') as outfile:
                    outfile.write(content)

                command = 'cat /root/.ssh/config'
                current_config = pu.outputExecutioner(command)

                tmp_file = '/home/cyberpanel/sshconfig'
                with open(tmp_file, 'w') as outfile:
                    if current_config.find('cat') == -1:
                        outfile.write(current_config)

                    content = "Host %s\n" \
                              "    IdentityFile ~/.ssh/cyberpanel\n" \
                              "    Port %s\n" % (ip_address, port)
                    if current_config.find(ip_address) == -1:
                        outfile.write(content)

                command = 'mv %s /root/.ssh/config' % tmp_file
                pu.executioner(command)

                command = 'chown root:root /root/.ssh/config'
                pu.executioner(command)

                final_dic = {'status': 1, 'error_message': 'None'}
            else:
                final_dic = {'status': 0, 'error_message': output}
            final_json = json.dumps(final_dic)
            return HttpResponse(final_json)

        if data['type'].lower() == IncBackupProvider.AWS.name.lower():
            path = Path(IncBackupPath.AWS.value)
            path.mkdir(exist_ok=True)

            access_key = data['AWS_ACCESS_KEY_ID']
            secret_key = data['AWS_SECRET_ACCESS_KEY']

            aws_file = path / access_key

            with open(aws_file, 'w') as outfile:
                outfile.write(secret_key)

            aws_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

            final_dic = {'status': 1}
            final_json = json.dumps(final_dic)
            return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)


def populate_current_records(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'addDeleteDestinations') == 0:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        data = json.loads(request.body)

        json_data = []
        if data['type'].lower() == IncBackupProvider.SFTP.name.lower():
            path = Path(IncBackupPath.SFTP.value)

            if path.exists():
                for item in path.iterdir():
                    with open(item, 'r') as infile:
                        _file = infile.readlines()
                        json_data.append({
                            'ip': _file[0].strip('\n'),
                            'port': _file[1],
                        })
            else:
                final_json = json.dumps({'status': 1, 'error_message': "None", "data": ''})
                return HttpResponse(final_json)

        if data['type'].lower() == IncBackupProvider.AWS.name.lower():
            path = Path(IncBackupPath.AWS.value)

            if path.exists():
                for item in path.iterdir():
                    json_data.append({'AWS_ACCESS_KEY_ID': item.name})
            else:
                final_json = json.dumps({'status': 1, 'error_message': "None", "data": ''})
                return HttpResponse(final_json)

        final_json = json.dumps({'status': 1, 'error_message': "None", "data": json_data})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def remove_destination(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'addDeleteDestinations') == 0:
            return ACLManager.loadErrorJson('destStatus', 0)

        data = json.loads(request.body)

        if 'IPAddress' in data:
            file_name = data['IPAddress']

            if data['type'].lower() == IncBackupProvider.SFTP.name.lower():
                dest_file = Path(IncBackupPath.SFTP.value) / file_name
                dest_file.unlink()

            if data['type'].lower() == IncBackupProvider.AWS.name.lower():
                dest_file = Path(IncBackupPath.AWS.value) / file_name
                dest_file.unlink()

        final_dic = {'status': 1, 'error_message': 'None'}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'destStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def fetch_current_backups(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        admin = Administrator.objects.get(pk=user_id)

        data = json.loads(request.body)
        backup_domain = data['websiteToBeBacked']

        if ACLManager.checkOwnership(backup_domain, admin, current_acl) == 1:
            pass
        else:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        if 'backupDestinations' in data:
            backup_destinations = data['backupDestinations']
            extra_args = {'website': backup_domain, 'backupDestinations': backup_destinations}

            if 'password' in data:
                extra_args['password'] = data['password']
            else:
                final_json = json.dumps({'status': 0, 'error_message': "Please supply the password."})
                return HttpResponse(final_json)

            start_job = IncJobs('Dummy', extra_args)
            return start_job.fetchCurrentBackups()
        else:
            website = Websites.objects.get(domain=backup_domain)
            backups = website.incjob_set.all()
            json_data = []
            for backup in reversed(backups):
                snapshots = []
                jobs = backup.jobsnapshots_set.all()
                for job in jobs:
                    snapshots.append({'type': job.type, 'snapshotid': job.snapshotid, 'destination': job.destination})
                json_data.append({'id': backup.id,
                                  'date': str(backup.date),
                                  'snapshots': snapshots
                                  })
            final_json = json.dumps({'status': 1, 'error_message': "None", "data": json_data})
            return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def submit_backup_creation(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        admin = Administrator.objects.get(pk=user_id)

        data = json.loads(request.body)
        backup_domain = data['websiteToBeBacked']
        backup_destinations = data['backupDestinations']

        if ACLManager.checkOwnership(backup_domain, admin, current_acl) == 1:
            pass
        else:
            return ACLManager.loadErrorJson('metaStatus', 0)

        temp_path = Path("/home/cyberpanel/") / str(randint(1000, 9999))

        extra_args = {}
        extra_args['website'] = backup_domain
        extra_args['tempPath'] = str(temp_path)
        extra_args['backupDestinations'] = backup_destinations
        extra_args['websiteData'] = data['websiteData'] if 'websiteData' in data else False
        extra_args['websiteEmails'] = data['websiteEmails'] if 'websiteEmails' in data else False
        extra_args['websiteSSLs'] = data['websiteSSLs'] if 'websiteSSLs' in data else False
        extra_args['websiteDatabases'] = data['websiteDatabases'] if 'websiteDatabases' in data else False

        start_job = IncJobs('createBackup', extra_args)
        start_job.start()

        time.sleep(2)

        final_json = json.dumps({'status': 1, 'error_message': "None", 'tempPath': str(temp_path)})
        return HttpResponse(final_json)
    except BaseException as msg:
        logging.writeToFile(str(msg))
        final_dic = {'status': 0, 'metaStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def get_backup_status(request):
    try:
        data = json.loads(request.body)

        status = data['tempPath']
        backup_domain = data['websiteToBeBacked']

        user_id, current_acl = _get_user_acl(request)
        admin = Administrator.objects.get(pk=user_id)
        if ACLManager.checkOwnership(backup_domain, admin, current_acl) == 1:
            pass
        else:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        if ACLManager.CheckStatusFilleLoc(status):
            pass
        else:
            data_ret = {'abort': 1, 'installStatus': 0, 'installationProgress': "100",
                        'currentStatus': 'Invalid status file.'}
            json_data = json.dumps(data_ret)
            return HttpResponse(json_data)

        ## file name read ends

        if os.path.exists(status):
            command = "cat " + status
            result = pu.outputExecutioner(command, 'cyberpanel')

            if result.find("Completed") > -1:

                ### Removing Files

                os.remove(status)

                final_json = json.dumps(
                    {'backupStatus': 1, 'error_message': "None", "status": result, "abort": 1})
                return HttpResponse(final_json)

            elif result.find("[5009]") > -1:
                ## removing status file, so that backup can re-run
                try:
                    os.remove(status)
                except:
                    pass

                final_json = json.dumps(
                    {'backupStatus': 1, 'error_message': "None", "status": result,
                     "abort": 1})
                return HttpResponse(final_json)
            else:
                final_json = json.dumps(
                    {'backupStatus': 1, 'error_message': "None", "status": result,
                     "abort": 0})
                return HttpResponse(final_json)
        else:
            final_json = json.dumps({'backupStatus': 1, 'error_message': "None", "status": 1, "abort": 0})
            return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'backupStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        logging.writeToFile(str(msg) + " [backupStatus]")
        return HttpResponse(final_json)

def delete_backup(request):
    try:

        user_id, current_acl = _get_user_acl(request)
        admin = Administrator.objects.get(pk=user_id)
        data = json.loads(request.body)
        backup_domain = data['websiteToBeBacked']

        if ACLManager.checkOwnership(backup_domain, admin, current_acl) == 1:
            pass
        else:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        backup_id = data['backupID']

        inc_job = IncJob.objects.get(id=backup_id)

        job = IncJobs(None, None)
        job.DeleteSnapShot(inc_job)

        inc_job.delete()

        final_dic = {'status': 1, 'error_message': 'None'}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'destStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def fetch_restore_points(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        admin = Administrator.objects.get(pk=user_id)
        data = json.loads(request.body)
        backup_domain = data['websiteToBeBacked']

        if ACLManager.checkOwnership(backup_domain, admin, current_acl) == 1:
            pass
        else:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        data = json.loads(request.body)
        job_id = data['id']

        inc_job = IncJob.objects.get(id=job_id)

        backups = inc_job.jobsnapshots_set.all()

        json_data = []
        for items in backups:
            json_data.append({'id': items.id,
                              'snapshotid': items.snapshotid,
                              'type': items.type,
                              'destination': items.destination,
                              })

        final_json = json.dumps({'status': 1, 'error_message': "None", "data": json_data})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def restore_point(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        admin = Administrator.objects.get(pk=user_id)

        data = json.loads(request.body)
        backup_domain = data['websiteToBeBacked']
        job_id = data['jobid']

        if ACLManager.checkOwnership(backup_domain, admin, current_acl) == 1:
            pass
        else:
            return ACLManager.loadErrorJson('metaStatus', 0)

        temp_path = Path("/home/cyberpanel/") / str(randint(1000, 9999))

        if data['reconstruct'] == 'remote':
            extraArgs = {}
            extraArgs['website'] = backup_domain
            extraArgs['jobid'] = job_id
            extraArgs['tempPath'] = str(temp_path)
            extraArgs['reconstruct'] = data['reconstruct']
            extraArgs['backupDestinations'] = data['backupDestinations']
            extraArgs['password'] = data['password']
            extraArgs['path'] = data['path']
        else:
            extraArgs = {}
            extraArgs['website'] = backup_domain
            extraArgs['jobid'] = job_id
            extraArgs['tempPath'] = str(temp_path)
            extraArgs['reconstruct'] = data['reconstruct']

        start_job = IncJobs('restorePoint', extraArgs)
        start_job.start()

        time.sleep(2)

        final_json = json.dumps({'status': 1, 'error_message': "None", 'tempPath': str(temp_path)})
        return HttpResponse(final_json)
    except BaseException as msg:
        logging.writeToFile(str(msg))
        final_dic = {'status': 0, 'metaStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)


def schedule_backups(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadError()

        websites = ACLManager.findAllSites(current_acl, user_id)

        destinations = _get_destinations(local=True)

        return def_renderer(request, 'IncBackups/backupSchedule.html',
                            {'websiteList': websites, 'destinations': destinations}, 'scheduleBackups')
    except BaseException as msg:
        logging.writeToFile(str(msg))
        return redirect(loadLoginPage)


def submit_backup_schedule(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('scheduleStatus', 0)

        data = json.loads(request.body)

        backup_dest = data['backupDestinations']
        backup_freq = data['backupFreq']
        backup_retention = data['backupRetention']
        backup_sites = data['websitesToBeBacked']

        backup_data = 1 if 'websiteData' in data else 0
        backup_emails = 1 if 'websiteEmails' in data else 0
        backup_databases = 1 if 'websiteDatabases' in data else 0

        backup_job = BackupJob(websiteData=backup_data, websiteDataEmails=backup_emails,
                               websiteDatabases=backup_databases, destination=backup_dest, frequency=backup_freq,
                               retention=backup_retention)
        backup_job.save()

        for site in backup_sites:
            backup_site_job = JobSites(job=backup_job, website=site)
            backup_site_job.save()

        final_json = json.dumps({'status': 1, 'error_message': "None"})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_json = json.dumps({'status': 0, 'error_message': str(msg)})
        return HttpResponse(final_json)


def get_current_backup_schedules(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        records = BackupJob.objects.all()

        json_data = []
        for items in records:
            json_data.append({'id': items.id,
                              'destination': items.destination,
                              'frequency': items.frequency,
                              'retention': items.retention,
                              'numberOfSites': items.jobsites_set.all().count()
                              })
        final_json = json.dumps({'status': 1, 'error_message': "None", "data": json_data})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)


def fetch_sites(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('fetchStatus', 0)

        data = json.loads(request.body)

        job = BackupJob.objects.get(pk=data['id'])

        json_data = []
        for jobsite in job.jobsites_set.all():
            json_data.append({'id': jobsite.id,
                              'website': jobsite.website,
                              })
        final_json = json.dumps({'status': 1, 'error_message': "None", "data": json_data,
                                 'websiteData': job.websiteData, 'websiteDatabases': job.websiteDatabases,
                                 'websiteEmails': job.websiteDataEmails})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)


def schedule_delete(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('scheduleStatus', 0)

        data = json.loads(request.body)

        job_id = data['id']

        backup_job = BackupJob.objects.get(id=job_id)
        backup_job.delete()

        final_json = json.dumps({'status': 1, 'error_message': "None"})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_json = json.dumps({'status': 0, 'error_message': str(msg)})
        return HttpResponse(final_json)


def restore_remote_backups(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'createBackup') == 0:
            return ACLManager.loadError()

        websites = ACLManager.findAllSites(current_acl, user_id)

        destinations = _get_destinations()

        return def_renderer(request, 'IncBackups/restoreRemoteBackups.html',
                            {'websiteList': websites, 'destinations': destinations}, 'createBackup')
    except BaseException as msg:
        logging.writeToFile(str(msg))
        return redirect(loadLoginPage)


def save_changes(request):
    try:
        user_id, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('scheduleStatus', 0)

        data = json.loads(request.body)

        job_id = data['id']

        backup_data = data['websiteData'] if 'websiteData' in data else 0
        backup_emails = data['websiteEmails'] if 'websiteEmails' in data else 0
        backup_databases = data['websiteDatabases'] if 'websiteDatabases' in data else 0

        job = BackupJob.objects.get(pk=job_id)

        job.websiteData = int(backup_data)
        job.websiteDatabases = int(backup_databases)
        job.websiteDataEmails = int(backup_emails)
        job.save()

        final_json = json.dumps({'status': 1, 'error_message': "None"})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_json = json.dumps({'status': 0, 'error_message': str(msg)})
        return HttpResponse(final_json)


def remove_site(request):
    try:
        _, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('scheduleStatus', 0)

        data = json.loads(request.body)

        job_id = data['id']
        website = data['website']
        job = BackupJob.objects.get(pk=job_id)
        site = JobSites.objects.get(job=job, website=website)
        site.delete()

        final_json = json.dumps({'status': 1, 'error_message': "None"})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_json = json.dumps({'status': 0, 'error_message': str(msg)})
        return HttpResponse(final_json)


def add_website(request):
    try:
        _, current_acl = _get_user_acl(request)
        if ACLManager.currentContextPermission(current_acl, 'scheduleBackups') == 0:
            return ACLManager.loadErrorJson('scheduleStatus', 0)

        data = json.loads(request.body)

        job_id = data['id']
        website = data['website']

        job = BackupJob.objects.get(pk=job_id)

        try:
            JobSites.objects.get(job=job, website=website)
        except BaseException:
            site = JobSites(job=job, website=website)
            site.save()

        final_json = json.dumps({'status': 1, 'error_message': "None"})
        return HttpResponse(final_json)
    except BaseException as msg:
        final_json = json.dumps({'status': 0, 'error_message': str(msg)})
        return HttpResponse(final_json)

#### Backups v2

def ConfigureV2Backup(request):
    try:
        user_id, current_acl = _get_user_acl(request)

        if ACLManager.currentContextPermission(current_acl, 'createBackup') == 0:
            return ACLManager.loadError()

        if ACLManager.CheckForPremFeature('all'):
            BackupStat = 1
        else:
            BackupStat = 0

        websites = ACLManager.findAllSites(current_acl, user_id)
        #
        # destinations = _get_destinations(local=True)
        proc = httpProc(request, 'IncBackups/ConfigureV2Backup.html', {'websiteList': websites, 'BackupStat': BackupStat})
        return proc.render()

    except BaseException as msg:
        logging.writeToFile(str(msg))
        return redirect(loadLoginPage)

def ConfigureV2BackupSetup(request):
    try:
        userID = request.session['userID']

        req_data={}
        req_data['name'] = 'GDrive'
        req_data['token'] = request.GET.get('t')
        req_data['refresh_token'] = request.GET.get('r')
        req_data['token_uri'] = request.GET.get('to')
        req_data['scopes'] = request.GET.get('s')
        req_data['accountname'] = request.GET.get('n')
        website = request.GET.get('d')

        # logging.writeToFile('domainname is ====%s'%(request.GET.get))

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)


        if ACLManager.checkOwnership(website, admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()

        cpbuv2 = CPBackupsV2(
            {'domain': website, 'BasePath': '/home/backup', 'BackupDatabase': 1, 'BackupData': 1,
             'BackupEmails': 1, 'BackendName': 'testremote'})

        cpbuv2.SetupRcloneBackend(CPBackupsV2.GDrive, req_data)

        return ConfigureV2Backup(request)

    except BaseException as msg:
        logging.writeToFile("Error configure"+str(msg))
        return redirect(loadLoginPage)

def CreateV2Backup(request):
    try:
        userID = request.session['userID']
        bm = BackupManager()
        return bm.CreateV2backupSite(request, userID)
    except KeyError:
        return redirect(loadLoginPage)


def DeleteRepoV2(request):
    try:
        userID = request.session['userID']
        bm = BackupManager()
        return bm.DeleteRepoV2(request, userID)
    except KeyError:
        return redirect(loadLoginPage)

def CreateV2BackupButton(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']
        Selectedrepo = data['Selectedrepo']


        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(Selectedwebsite, admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()


        extra_args = {}
        extra_args['function'] = 'InitiateBackup'
        extra_args['website'] = Selectedwebsite
        extra_args['domain'] = Selectedwebsite
        extra_args['BasePath'] = '/home/backup'
        extra_args['BackendName'] = Selectedrepo
        extra_args['BackupData'] = data['websiteData'] if 'websiteData' in data else False
        extra_args['BackupEmails'] = data['websiteEmails'] if 'websiteEmails' in data else False
        extra_args['BackupDatabase'] = data['websiteDatabases'] if 'websiteDatabases' in data else False

        background = CPBackupsV2(extra_args)
        background.start()

        # background = CPBackupsV2({'domain': Selectedwebsite, 'BasePath': '/home/backup', 'BackupDatabase': 1, 'BackupData': 1,
        #      'BackupEmails': 1, 'BackendName': Selectedrepo, 'function': 'InitiateBackup', })
        # background.start()

        time.sleep(2)

        data_ret = {'status': 1, 'installStatus': 1, 'error_message': 'None',}
        json_data = json.dumps(data_ret)
        return HttpResponse(json_data)

    except BaseException as msg:
        data_ret = {'status': 0, 'installStatus': 0, 'error_message': str(msg)}
        json_data = json.dumps(data_ret)
        return HttpResponse(json_data)

def CreateV2BackupStatus(request):
    try:
        userID = request.session['userID']
        bm = BackupManager()
        return bm.CreateV2BackupStatus(userID, json.loads(request.body))
    except KeyError:
        return redirect(loadLoginPage)

def RestoreV2backupSite(request):
    try:
        userID = request.session['userID']
        bm = BackupManager()
        return bm.RestoreV2backupSite(request, userID)
    except KeyError:
        return redirect(loadLoginPage)

def RestorePathV2(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        SnapShotId = data['snapshotid']
        Path = data['path']
        Selectedwebsite = data['selwebsite']
        Selectedrepo = data['selectedrepo']

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()

        extra_args = {}
        extra_args['function'] = 'InitiateRestore'
        extra_args['website'] = Selectedwebsite
        extra_args['domain'] = Selectedwebsite
        extra_args['BasePath'] = '/home/backup'
        extra_args['BackendName'] = Selectedrepo
        extra_args['path'] = Path
        extra_args['snapshotid'] = SnapShotId
        # extra_args['BackupData'] = data['websiteData'] if 'websiteData' in data else False
        # extra_args['BackupEmails'] = data['websiteEmails'] if 'websiteEmails' in data else False
        # extra_args['BackupDatabase'] = data['websiteDatabases'] if 'websiteDatabases' in data else False


        background = CPBackupsV2(extra_args)
        background.start()

        # vm = CPBackupsV2({'domain': Selectedwebsite, 'BackendName': Selectedrepo, "function": "", 'BasePath': '/home/backup'})
        # status = vm.InitiateRestore(SnapShotId, Path)

        data_ret = {'status': 1, 'installStatus': 1, 'error_message': 'None',}
        json_data = json.dumps(data_ret)
        return HttpResponse(json_data)

    except BaseException as msg:
        data_ret = {'status': 0, 'installStatus': 0, 'error_message': str(msg)}
        json_data = json.dumps(data_ret)
        return HttpResponse(json_data)

def selectwebsiteRetorev2(request):
    import re
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()

        obj = Websites.objects.get(domain = str(Selectedwebsite))
        #/home/cyberpanel.net/.config/rclone/rclone.conf
        path = '/home/%s/.config/rclone/rclone.conf' %(obj.domain)

        command = 'cat %s'%(path)
        result = pu.outputExecutioner(command)

        if result.find('type') > -1:
            pattern = r'\[(.*?)\]'
            matches = re.findall(pattern, result)
            final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": matches})
            return HttpResponse(final_json)
        else:
            final_json = json.dumps({'status': 0, 'fetchStatus': 0, 'error_message': 'Could not Find repo'})
            return HttpResponse(final_json)


        # final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": 1})
        # return HttpResponse(final_json)
    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def ConfigureSftpV2Backup(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']
        sfptpasswd = data['sfptpasswd']
        hostName = data['hostName']
        UserName = data['UserName']
        Repo_Name = data['Repo_Name']
        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()

        req_data = {}
        req_data['name'] = 'SFTP'
        req_data['host'] = hostName
        req_data['user'] = UserName
        req_data['password'] = sfptpasswd
        req_data['Repo_Name'] = Repo_Name


        cpbuv2 = CPBackupsV2(
            {'domain': Selectedwebsite, 'BasePath': '/home/backup', 'BackupDatabase': 1, 'BackupData': 1,
             'BackupEmails': 1, 'BackendName': 'SFTP', 'function': None})

        cpbuv2.SetupRcloneBackend(CPBackupsV2.SFTP, req_data)

        # return ConfigureV2Backup(request)

        final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": None})
        return HttpResponse(final_json)


    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def selectwebsiteCreatev2(request):
    import re
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()

        obj = Websites.objects.get(domain = str(Selectedwebsite))
        #/home/cyberpanel.net/.config/rclone/rclone.conf
        path = '/home/%s/.config/rclone/rclone.conf' %(obj.domain)

        command = 'cat %s'%(path)
        CurrentContent = pu.outputExecutioner(command)

        status, currentSchedules = CPBackupsV2.FetchCurrentSchedules(str(Selectedwebsite))


        if CurrentContent.find('No such file or directory') > -1:
            LocalRclonePath = f'/home/{obj.domain}/.config/rclone'
            command = f'mkdir -p {LocalRclonePath}'
            pu.executioner(command, obj.externalApp)

            # content = '''
            #        [local]
            #        type = local
            #        '''
            # command = f"echo '{content}' > {path}"
            # pu.executioner(command, obj.externalApp, True)

            command = 'cat %s' % (path)
            result = pu.outputExecutioner(command)

            if result.find('type') > -1:
                pattern = r'\[(.*?)\]'
                matches = re.findall(pattern, result)
                final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": matches, 'currentSchedules': currentSchedules})
                return HttpResponse(final_json)
            else:
                final_json = json.dumps({'status': 0, 'fetchStatus': 0, 'error_message': 'Could not Find repo'})
                return HttpResponse(final_json)
        else:
            command = 'cat %s' % (path)
            result = pu.outputExecutioner(command)

            if result.find('type') > -1:
                pattern = r'\[(.*?)\]'
                matches = re.findall(pattern, result)
                final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": matches, 'currentSchedules': currentSchedules})
                return HttpResponse(final_json)
            else:
                final_json = json.dumps({'status': 0, 'fetchStatus': 0, 'error_message': 'Could not Find repo', 'currentSchedules': currentSchedules})
                return HttpResponse(final_json)


        # logging.writeToFile(str(CurrentContent))
        # final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": None})
        # return HttpResponse(final_json)
        #


    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def selectreporestorev2(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedrepo = data['Selectedrepo']
        Selectedwebsite= data['Selectedwebsite']
        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()


        # f'rustic -r testremote snapshots --password "" --json 2>/dev/null'
        # final_json = json.dumps({'status': 0, 'fetchStatus': 1, 'error_message': Selectedrepo })
        # return HttpResponse(final_json)

        vm = CPBackupsV2({'domain': Selectedwebsite, 'BackendName': Selectedrepo, "function":""})
        status, data = vm.FetchSnapShots()

        if status == 1:
            final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": data})
            return HttpResponse(final_json)
        else:
            # final_json = json.dumps({'status': 0, 'fetchStatus': 1, 'error_message': ac,})
            final_json = json.dumps({'status': 0, 'fetchStatus': 1, 'error_message': 'Cannot Find!',})
            return HttpResponse(final_json)


    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def schedulev2Backups(request):
    try:
        userID = request.session['userID']
        bm = BackupManager()
        return bm.schedulev2Backups(request, userID)
    except KeyError:
        return redirect(loadLoginPage)

def DeleteScheduleV2(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']
        repo = data['repo']
        frequency = data['frequency']
        websiteData = data['websiteData']
        websiteDatabases = data['websiteDatabases']
        websiteEmails = data['websiteEmails']

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()


        status, message = CPBackupsV2.DeleteSchedule(Selectedwebsite, repo, frequency, websiteData, websiteDatabases, websiteEmails)

        final_dic = {'status': 1, 'error_message': message}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

        # final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": None})
        # return HttpResponse(final_json)


    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

def CreateScheduleV2(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']
        repo = data['repo']
        frequency = data['frequency']
        retention = data['retention']
        websiteData = data['websiteData'] if 'websiteData' in data else False
        websiteDatabases = data['websiteDatabases'] if 'websiteDatabases' in data else False
        websiteEmails = data['websiteEmails'] if 'websiteEmails' in data else False

        #
        # extra_args['BackupData'] = data['websiteData'] if 'websiteData' in data else False
        # extra_args['BackupEmails'] = data['websiteEmails'] if 'websiteEmails' in data else False
        # extra_args['BackupDatabase'] = data['websiteDatabases'] if 'websiteDatabases' in data else False

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()


        status, message = CPBackupsV2.CreateScheduleV2(Selectedwebsite, repo, frequency, websiteData, websiteDatabases, websiteEmails, retention)

        final_dic = {'status': 1, 'error_message': message}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)

        # final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": None})
        # return HttpResponse(final_json)


    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)



def DeleteV2BackupButton(request):
    try:
        userID = request.session['userID']
        data = json.loads(request.body)
        Selectedwebsite = data['Selectedwebsite']
        repo = data['Selectedrepo']

        currentACL = ACLManager.loadedACL(userID)
        admin = Administrator.objects.get(pk=userID)

        if ACLManager.checkOwnership(str(Selectedwebsite), admin, currentACL) == 1:
            pass
        else:
            return ACLManager.loadError()


        obj = Websites.objects.get(domain=Selectedwebsite)
        usr= obj.externalApp

        status, message = CPBackupsV2.DeleteRepoScheduleV2(Selectedwebsite, repo, usr)

        if status == 1:
            final_dic = {'status': 1, 'error_message': message}
            final_json = json.dumps(final_dic)
            return HttpResponse(final_json)
        else:
            final_dic = {'status': 0, 'error_message': message}
            final_json = json.dumps(final_dic)
            return HttpResponse(final_json)

        # final_json = json.dumps({'status': 1, 'fetchStatus': 1, 'error_message': "None", "data": None})
        # return HttpResponse(final_json)


    except BaseException as msg:
        final_dic = {'status': 0, 'fetchStatus': 0, 'error_message': str(msg)}
        final_json = json.dumps(final_dic)
        return HttpResponse(final_json)